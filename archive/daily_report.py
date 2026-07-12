"""每日运行报告 —— 统计当天的消息、记忆、错误数量。

纯数据统计，不使用 AI 总结。
"""

from datetime import datetime
from pathlib import Path


ARCHIVE_ROOT = Path(__file__).resolve().parent.parent / "archives"
REPORT_DIR = ARCHIVE_ROOT / "daily_reports"


def generate() -> str | None:
    """生成今天的运行报告。

    Returns:
        报告文件路径，失败返回 None
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORT_DIR / f"{today}.md"

        # 统计对话
        conv_dir = ARCHIVE_ROOT / "conversations" / str(datetime.now().year) / f"{datetime.now().month:02d}"
        conv_file = conv_dir / f"{today}.md"
        msg_count = 0
        if conv_file.exists():
            with open(conv_file, "r", encoding="utf-8") as f:
                msg_count = f.read().count("**User:**")

        # 统计记忆事件
        mem_file = ARCHIVE_ROOT / "memory_events" / f"{today}.json"
        mem_count = 0
        if mem_file.exists():
            with open(mem_file, "r", encoding="utf-8") as f:
                mem_count = sum(1 for _ in f)

        # 统计错误
        err_file = ARCHIVE_ROOT / "errors" / f"{today}.log"
        err_count = 0
        if err_file.exists():
            with open(err_file, "r", encoding="utf-8") as f:
                err_count = f.read().count("Module:")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# Daily Report\n\nDate: {today}\n\n")
            f.write(f"- Chat Messages: {msg_count}\n")
            f.write(f"- Memory Events: {mem_count}\n")
            f.write(f"- Errors: {err_count}\n\n")
            f.write("Notes:\n\n")

        return str(report_path)

    except Exception:
        return None
