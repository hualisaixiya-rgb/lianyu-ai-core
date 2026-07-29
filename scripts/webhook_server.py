"""GitHub Webhook 接收器。

独立运行在配置的端口上（默认 9000），
接收 GitHub push 事件后自动触发部署脚本。

依赖：仅 Python 标准库 + PyYAML（已在项目依赖中）。
不依赖 FastAPI / uvicorn，不受 LianyuAI 重启影响。

配置来源：
    config/deploy.yaml   — 端口、分支、去重、锁超时（提交）
    .env.deploy          — WEBHOOK_SECRET、TUNNEL_HOSTNAME（服务器本地）

安全机制：
    - HMAC-SHA256 签名校验（.env.deploy 读取 secret）
    - 仅接受 push 事件
    - 仅触发 main 分支
    - 相同 HEAD 不重复部署
    - 锁文件防止并发部署
    - 非法请求返回 403
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

import yaml


# ---- 常量 ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_FILE = PROJECT_ROOT / "config" / "deploy.yaml"
SECRET_FILE = PROJECT_ROOT / ".env.deploy"
LAST_HEAD_FILE = PROJECT_ROOT / ".deploy.last_head"
LOCK_FILE = PROJECT_ROOT / ".deploy.lock"

DEPLOY_SCRIPT = PROJECT_ROOT / "scripts" / "deploy.ps1"


def load_config() -> dict:
    """加载 deploy.yaml 配置。"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    sys.exit("❌ config/deploy.yaml 缺失")


def load_secret() -> str:
    """从 .env.deploy 读取 WEBHOOK_SECRET（不进入 Git）。"""
    if not SECRET_FILE.exists():
        sys.exit("❌ .env.deploy 缺失，请先在服务器创建")

    for line in SECRET_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("WEBHOOK_SECRET="):
            secret = line.split("=", 1)[1].strip().strip('"').strip("'")
            if secret and secret != "在此填入随机32位密钥":
                return secret
    sys.exit("❌ .env.deploy 中未配置 WEBHOOK_SECRET")


def load_last_head() -> Optional[str]:
    """读取上次成功部署的 HEAD。"""
    if LAST_HEAD_FILE.exists():
        return LAST_HEAD_FILE.read_text().strip()
    return None


def save_last_head(head: str) -> None:
    """保存本次成功部署的 HEAD。"""
    LAST_HEAD_FILE.write_text(head)


def write_log(msg: str) -> None:
    """写部署日志。"""
    log_dir = PROJECT_ROOT / "logs" / "deploy"
    log_dir.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().isoformat()}] {msg}"
    with open(log_dir / "webhook.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def acquire_lock(timeout: int) -> bool:
    """获取部署锁。

    如果锁文件存在且未超时 → 拒绝（已有部署进行中）。
    如果锁文件超时 → 强制释放，获取新锁。
    """
    try:
        if LOCK_FILE.exists():
            mtime = LOCK_FILE.stat().st_mtime
            age = time.time() - mtime
            if age < timeout:
                write_log(f"⛔ 部署锁占用中（{int(age)}s 前，超时={timeout}s），拒绝并发热部署")
                return False
            else:
                write_log(f"⚠️  锁文件超时（{int(age)}s），强制释放")
                LOCK_FILE.unlink(missing_ok=True)

        LOCK_FILE.touch()
        return True
    except Exception as e:
        write_log(f"❌ 获取锁失败: {e}")
        return False


def release_lock() -> None:
    """释放部署锁。"""
    LOCK_FILE.unlink(missing_ok=True)


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    """验证 GitHub HMAC-SHA256 签名。"""
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


class WebhookHandler(BaseHTTPRequestHandler):
    """Webhook HTTP 请求处理器。"""

    secret: str = ""
    config: dict = {}

    def do_GET(self) -> None:
        """健康检查端点（Cloudflare Tunnel 也需要）。"""
        if self.path in ("/health", "/"):
            self._respond(200, {"status": "ok", "service": "LianyuDeploy"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self) -> None:
        """处理 Webhook 请求。"""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        # ---------- 安全校验 ----------

        # 1. HMAC 签名校验（必须）
        signature = self.headers.get("X-Hub-Signature-256")
        if not verify_signature(self.secret, body, signature):
            write_log("🔒 签名验证失败 → 403")
            self._respond(403, {"error": "invalid signature"})
            return

        # 2. 仅接受配置中允许的事件
        event = self.headers.get("X-GitHub-Event", "")
        allowed_events = self.config.get("webhook", {}).get("allowed_events", ["push"])
        if event not in allowed_events:
            write_log(f"⏭️  事件类型 {event} 不在允许列表，跳过")
            self._respond(200, {"status": "skipped", "reason": f"event={event}"})
            return

        # 3. Ping 事件（GitHub 配置验证）
        if event == "ping":
            write_log("📡 Ping 成功 — GitHub Webhook 配置正确")
            self._respond(200, {"status": "pong"})
            return

        # 4. 解析 payload
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            write_log("⚠️  无效 JSON payload → 400")
            self._respond(400, {"error": "invalid json"})
            return

        ref = payload.get("ref", "")
        after = payload.get("after", "")

        # 5. 仅允许配置中指定的分支
        allowed_branches = self.config.get("webhook", {}).get("allowed_branches", [])

        if ref not in allowed_branches:
            write_log(f"⏭️  分支 {ref} 不在允许列表，跳过")
            self._respond(200, {"status": "skipped", "reason": f"ref={ref}"})
            return

        # 6. HEAD 去重：相同 HEAD 不重复部署
        if self.config.get("webhook", {}).get("dedup", True):
            last_head = load_last_head()
            if last_head and last_head == after:
                write_log(f"⏭️  HEAD 未变化 ({after[:7]})，跳过部署")
                self._respond(200, {"status": "skipped", "reason": "head unchanged"})
                return

        # 7. 并发锁检查
        lock_timeout = self.config.get("deploy", {}).get("lock_timeout_seconds", 600)
        if not acquire_lock(lock_timeout):
            self._respond(503, {"error": "deploy in progress"})
            return

        # ---------- 启动部署 ----------
        write_log(f"🚀 启动部署: {ref} → {after[:7]}")

        # 写入 HEAD 到文件供 deploy.ps1 读取
        LAST_HEAD_FILE.write_text(f"{after}\npending")

        subprocess.Popen(
            [
                "powershell.exe",
                "-ExecutionPolicy", "Bypass",
                "-File", str(DEPLOY_SCRIPT),
                "-TargetHead", after,
            ],
            cwd=str(PROJECT_ROOT),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        self._respond(200, {"status": "deploy started"})

    # ---------- 辅助方法 ----------

    def _respond(self, code: int, data: dict) -> None:
        """发送 JSON 响应。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """禁用默认 HTTP 访问日志（改用我们自己的日志）。"""
        pass


def main():
    config = load_config()

    port = config.get("webhook", {}).get("port", 9000)
    listen = config.get("webhook", {}).get("listen", "0.0.0.0")

    # 日志目录初始化
    log_dir = PROJECT_ROOT / "logs" / "deploy"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 注入配置到 Handler
    WebhookHandler.secret = load_secret()
    WebhookHandler.config = config

    write_log(f"LianyuDeploy 启动 | 端口 {port} | 分支 {config.get('webhook', {}).get('allowed_branches', [])}")

    server = HTTPServer((listen, port), WebhookHandler)
    print(f"LianyuDeploy 已启动，监听 {listen}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        write_log("LianyuDeploy 已停止")
        server.server_close()


if __name__ == "__main__":
    main()
