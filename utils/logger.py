"""日志系统初始化。

基于 Loguru，支持：
- 控制台彩色输出
- 按天切割日志文件
- 自动创建日志目录
"""

import sys
from pathlib import Path

from loguru import logger


def setup_logger(log_level: str = "INFO") -> None:
    """初始化日志系统。

    配置 Loguru 全局 logger：
    - 移除默认 handler
    - 添加控制台彩色输出
    - 添加按天轮转的文件日志

    Args:
        log_level: 日志级别，如 "DEBUG", "INFO", "WARNING", "ERROR"
    """
    logger.remove()

    # 控制台输出：彩色格式
    logger.add(
        sys.stderr,
        level=log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # 文件输出：保留最近 30 天日志
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        logs_dir / "lianyu_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",
        encoding="utf-8",
        enqueue=True,  # 多进程安全
    )

    logger.info(f"日志系统已初始化，级别: {log_level}")


def get_logger():
    """获取 Loguru logger 实例。

    Returns:
        loguru.Logger 实例，可直接用于 logger.info(...) 等调用
    """
    return logger
