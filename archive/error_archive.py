"""错误归档 —— 捕获并记录系统异常。

在异常处理位置调用 record()，追加到当天日志文件。
"""

from datetime import datetime
from pathlib import Path

from loguru import logger

ARCHIVE_ROOT = Path(__file__).resolve().parent.parent / "archives" / "errors"


def _get_today_file() -> Path:
    now = datetime.now()
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    return ARCHIVE_ROOT / f"{now.strftime('%Y-%m-%d')}.log"


def record(
    module: str,
    error_msg: str,
    detail: str = "",
) -> None:
    """记录一条错误。

    Args:
        module: 发生错误的模块名
        error_msg: 错误简述
        detail: 详细堆栈或上下文
    """
    try:
        filepath = _get_today_file()
        now = datetime.now().strftime("%H:%M:%S")
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"[{now}] Module: {module}\nError: {error_msg}\n")
            if detail:
                f.write(f"Detail: {detail}\n")
            f.write("\n")

    except Exception as e:
        logger.warning(f"错误归档失败: {e}")
