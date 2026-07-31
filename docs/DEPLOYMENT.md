# LianyuAI Core — 部署文档

## 服务器架构

```
GitHub (main) ──Webhook──> LianyuDeploy (:9000) ──deploy.ps1──> LianyuAI (:8000)
                                                                LianyuTelegram
```

| 服务 | 端口 | 账号 | 管理方式 | 说明 |
|------|------|------|----------|------|
| **LianyuDeploy** | 9000 | SYSTEM (via NSSM) | `nssm status/start/stop LianyuDeploy` | Webhook 接收器 + 自动部署 |
| **LianyuAI** | 8000 | SYSTEM (via NSSM) | `nssm status/start/stop LianyuAI` | AI 推理引擎 |
| **LianyuTelegram** | — | SYSTEM (via NSSM) | `nssm status/start/stop LianyuTelegram` | Telegram Bot |

---

## 自动部署流程

```
GitHub Push (main)
  └─> POST :9000  (HMAC-SHA256 签名验证)
      └─> webhook_server.py
          ├── 1. 签名校验 (X-Hub-Signature-256)
          ├── 2. 事件过滤 (push only)
          ├── 3. 分支过滤 (refs/heads/main only)
          ├── 4. HEAD 去重 (相同 commit 不重复部署)
          ├── 5. 并发锁 (10 分钟超时)
          └─> deploy.ps1 -TargetHead <sha>
              ├── [1/5] git pull origin main
              ├── [2/5] uv sync --no-dev
              ├── [3/5] NSSM restart LianyuAI + LianyuTelegram
              ├── [4/5] Health check (3 retries x 5s)
              ├── [5/5] Chat API smoke test
              └── 任一失败 → git reset --hard + 自动回滚
```

---

## 配置文件

| 文件 | 用途 | Git |
|------|------|-----|
| `config/deploy.yaml` | Webhook 端口、允许事件、分支、去重、锁超时、健康检查参数 | ✅ 提交 |
| `.env.deploy` | `WEBHOOK_SECRET`（HMAC 密钥） | ❌ gitignored |
| `logs/deploy/webhook.log` | Webhook 接收日志 | ❌ 运行数据 |
| `logs/deploy/deploy.log` | 部署执行日志 | ❌ 运行数据 |

---

## 部署测试方法

### 手动部署

```powershell
cd E:\AI\lianyu-ai-core
powershell -ExecutionPolicy Bypass -File .\scripts\deploy.ps1
```

### 模拟 GitHub Webhook

```powershell
cd E:\AI\lianyu-ai-core
.venv\Scripts\python.exe scripts\_trigger_deploy.py
```

### 查看日志

```powershell
# Webhook 日志
Get-Content logs\deploy\webhook.log -Encoding UTF8 -Tail 20

# 部署日志
Get-Content logs\deploy\deploy.log -Encoding UTF8 -Tail 30

# NSSM 进程输出
Get-Content logs\webhook_stdout.log -Encoding UTF8
```

---

## 已解决的问题

### 1. PowerShell 5.1 — Emoji 编码导致解析失败

**症状**：`ParserError: Try statement missing its own Catch or Finally block`

**原因**：Windows PowerShell 5.1 无法正确解析包含 4 字节 UTF-8 emoji 字符（✅⚠️🚀⏭️）的 `.ps1` 文件。

**解决**：所有 emoji 替换为 ASCII 安全标签：
- `✅` → `[OK]`
- `❌` → `[FAIL]`
- `⚠️` → `[WARN]`
- `⏭️` → `[SKIP]`
- `↩️` → `[ROLLBACK]`

---

### 2. PowerShell 5.1 — `2>&1 | ForEach-Object` ErrorRecord 异常

**症状**：`git pull` 返回 `Already up to date.` 但脚本捕获到异常：
```
[FAIL] git pull failed: From https://github.com/...
```

**原因**：PowerShell 5.1 将原生命令的 stderr 行包装为 `ErrorRecord` 对象。当 ErrorRecord 传给 `[string]` 类型函数参数时，`$ErrorActionPreference = "Stop"` 导致引擎抛出终止错误。

**验证**：
```powershell
# 修复前（抛出异常）
$output = git pull origin main 2>&1    # output[0] 类型: ErrorRecord
foreach ($line in $output) { Write-Log "  $line" }  # 异常!

# 修复后（正常）
$output = cmd /c "git pull origin main 2>&1"  # output[0] 类型: String
foreach ($line in $output) { Write-Log "  $line" }  # OK
```

**解决**：所有原生命令（git、uv、nssm）改用 `cmd /c "command 2>&1"`，在 OS 句柄层合并 stderr，PowerShell 收到纯文本。

---

### 3. SYSTEM 账户 PATH — uv 找不到

**症状**：
```
'uv' 不是内部或外部命令，也不是可运行的程序
```

**原因**：LianyuDeploy 以 `NT AUTHORITY\SYSTEM` 运行，`uv` 安装在 `C:\Users\huali\.local\bin\`，不在 SYSTEM 的 PATH 中。

**解决**：`deploy.ps1` 启动时自动检测 `uv`，依次尝试：
1. `uv` (PATH)
2. `C:\Users\huali\.local\bin\uv.exe`
3. `%USERPROFILE%\.local\bin\uv.exe`
4. 项目 `.venv\Scripts\uv.exe`

---

### 4. SYSTEM 账户 PATH — nssm 找不到

**症状**：同上，`nssm` 通过 winget 安装在用户 AppData 下。

**原因**：`$env:LOCALAPPDATA` 在 SYSTEM 上下文解析为 `C:\Windows\system32\config\systemprofile\AppData`，而非安装用户的路径。

**解决**：`deploy.ps1` 启动时自动检测 `nssm`，依次尝试：
1. `nssm` (PATH)
2. `%ProgramFiles%\nssm\win64\nssm.exe`
3. `%ProgramFiles(x86)%\nssm\win64\nssm.exe`
4. winget 包目录通配搜索 (`NSSM.NSSM_*\**\nssm.exe`)
5. 硬编码 huali 用户 winget 路径通配

---

### 5. Git — SYSTEM 账户 dubious ownership

**症状**：
```
fatal: detected dubious ownership in repository at 'E:/AI/lianyu-ai-core'
```

**原因**：Git 2.35.2+ 的安全检查 — 仓库归 `DESKTOP-279657F\huali` 所有，但 SYSTEM 账户在操作。

**解决**：
```powershell
git config --system --add safe.directory "E:/AI/lianyu-ai-core"
```
系统级配置对 SYSTEM 账户生效。

---

### 6. Python — GBK 编码解码 UTF-8 BOM

**症状**：
```
UnicodeDecodeError: 'gbk' codec can't decode byte 0xbf
```

**原因**：`deploy.ps1` 使用 `Out-File -Encoding utf8` 写入 `.deploy.last_head`（含 BOM），Python 的 `Path.read_text()` 默认系统编码 GBK，无法解析 BOM。

**状态**：`webhook_server.py` 的 `load_last_head()` / `save_last_head()` 需要显式指定 `encoding="utf-8"`。当前为已知问题，下次部署成功后可能重现。

---

## 运维命令速查

```powershell
# 服务管理
nssm status LianyuDeploy
nssm status LianyuAI
nssm status LianyuTelegram
nssm restart LianyuDeploy

# 端口检查
netstat -ano | findstr ":9000"
netstat -ano | findstr ":8000"

# 健康检查
curl http://localhost:9000/health
curl http://localhost:8000/api/v1/health

# 锁文件清理（部署卡死时）
Remove-Item E:\AI\lianyu-ai-core\.deploy.lock -Force
Remove-Item E:\AI\lianyu-ai-core\.deploy.last_head -Force
```

---

## 部署环境要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Windows | 10 Pro 19045 | 服务器运行环境 |
| Git | 2.55.0+ | `git config --system safe.directory` 配置 |
| Python | 3.12.10 | 项目 `.venv` |
| uv | 0.11.26+ | 包管理（自动检测路径） |
| NSSM | 2.24+ | 服务管理（自动检测路径） |
| cloudflared | 2026.7.3+ | Cloudflare Tunnel（待配置） |
