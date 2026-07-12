"""每日对话归档 —— 独立模块，不影响聊天流程。

在 AI 回复成功后调用 save()，追加写入当天的 Markdown 文件。
"""

import os
from datetime import datetime
from pathlib import Path

from loguru import logger

# 归档根目录
ARCHIVE_ROOT = Path(__file__).resolve().parent.parent / "archives" / "conversations"


def _get_today_file() -> Path:
    """获取当天的归档文件路径，按 YYYY/MM/YYYY-MM-DD.md 组织。"""
    now = datetime.now()
    year_dir = ARCHIVE_ROOT / str(now.year)
    month_dir = year_dir / f"{now.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir / f"{now.strftime('%Y-%m-%d')}.md"


def save(
    platform: str,
    user_id: str,
    username: str,
    user_message: str,
    ai_reply: str,
) -> None:
    """追加一条对话记录到当天的归档文件。

    Args:
        platform: 平台标识
        user_id: 用户 ID
        username: 用户名
        user_message: 用户消息
        ai_reply: AI 回复
    """
    try:
        filepath = _get_today_file()
        now = datetime.now().strftime("%H:%M:%S")
        is_new = not filepath.exists()

        with open(filepath, "a", encoding="utf-8") as f:
            if is_new:
                f.write(f"# Conversation Archive\n\nDate: {datetime.now().strftime('%Y-%m-%d')}\n\n")
                f.write(f"Platform: {platform} | User: {username} ({user_id})\n\n---\n\n")

            f.write(f"## {now}\n\n")
            f.write(f"**User:**\n\n{user_message}\n\n")
            f.write(f"**Assistant:**\n\n{ai_reply}\n\n")
            f.write("---\n\n")

    except Exception as e:
        logger.warning(f"对话归档失败: {e}")
