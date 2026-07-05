"""应用生命周期管理。

管理应用启动和关闭时的初始化/清理工作。
"""

from loguru import logger

from config.settings import get_settings
from database.engine import init_db, get_engine


async def startup() -> None:
    """应用启动回调。

    按顺序执行：
    1. 初始化数据库表
    2. 打印启动信息
    """
    settings = get_settings()
    logger.info("=" * 50)
    logger.info("绘梨衣 AI Core 启动中...")

    # 1. 初始化数据库（自动创建表）
    try:
        await init_db()
        logger.info("数据库表初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise

    logger.info(f"调试模式: {settings.app.debug}")
    logger.info(f"LLM 模型: {settings.ai.model}")
    logger.info(f"数据库: {settings.database.url}")
    logger.info(f"角色: {settings.character.name}")
    logger.info("=" * 50)

    logger.info("应用启动完成。")


async def shutdown() -> None:
    """应用关闭回调。

    按顺序执行：
    1. 关闭数据库连接
    2. 清理资源
    """
    logger.info("应用正在关闭...")

    # 关闭数据库引擎
    try:
        engine = get_engine()
        await engine.dispose()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.error(f"关闭数据库连接失败: {e}")

    logger.info("应用已关闭。")
