"""数据库引擎管理。

负责创建 SQLAlchemy 异步引擎、初始化表结构。
"""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import get_settings, PROJECT_ROOT
from database.models.base import Base


_engine = None
_session_factory = None


def get_engine():
    """获取或创建数据库异步引擎（单例）。

    Returns:
        SQLAlchemy AsyncEngine 实例
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        # 确保数据库文件目录存在
        _ensure_data_dir(settings.database.url)
        _engine = create_async_engine(
            settings.database.url,
            echo=settings.app.debug,
            future=True,
        )
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """获取异步会话工厂。

    Returns:
        async_sessionmaker 实例
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


def _ensure_data_dir(database_url: str) -> None:
    """确保 SQLite 数据库文件所在目录存在。

    从数据库 URL 中提取文件路径，创建其父目录。

    Args:
        database_url: SQLAlchemy 数据库 URL，如 "sqlite+aiosqlite:///data/lianyu.db"
    """
    # 提取路径部分：sqlite+aiosqlite:///data/lianyu.db -> data/lianyu.db
    if "///" in database_url:
        db_path = database_url.split("///", 1)[1]
        # 解析为绝对路径（相对于项目根目录）
        full_path = Path(db_path)
        if not full_path.is_absolute():
            full_path = PROJECT_ROOT / db_path
        parent = full_path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)


async def init_db() -> None:
    """初始化数据库表结构。

    根据所有继承自 Base 的 ORM 模型自动创建表。
    仅在表不存在时创建，不会覆盖已有数据。
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
