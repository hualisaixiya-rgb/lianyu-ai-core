"""记忆事件归档 —— 记录所有 Memory/Timeline 写入操作。

在记忆写入成功后调用 record()，追加 JSON 行到当天文件。
"""

import json
from datetime import datetime
from pathlib import Path

from loguru import logger

ARCHIVE_ROOT = Path(__file__).resolve().parent.parent / "archives" / "memory_events"


def _get_today_file() -> Path:
    now = datetime.now()
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    return ARCHIVE_ROOT / f"{now.strftime('%Y-%m-%d')}.json"


def record(
    operation: str,
    memory_type: str,
    content: str,
    source: str = "",
    confidence: int | str = "",
    platform: str = "",
    user_id: str = "",
) -> None:
    """记录一条记忆写入事件。

    Args:
        operation: create / update / confirm / merge
        memory_type: profile / timeline / long_memory / relationship_memory
        content: 记忆内容摘要
        source: 来源（extractor / summarizer / user / consolidation）
        confidence: 置信度
        platform: 平台
        user_id: 用户 ID
    """
    try:
        filepath = _get_today_file()
        event = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operation": operation,
            "memory_type": memory_type,
            "content": content[:200],
            "source": source,
            "confidence": str(confidence),
            "platform": platform,
            "user_id": user_id,
        }
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    except Exception as e:
        logger.warning(f"记忆归档失败: {e}")
