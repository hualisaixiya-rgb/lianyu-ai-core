"""数据库模块。

使用 SQLAlchemy 2.0 异步风格。
所有模型继承自 Base，便于统一管理元数据。
"""

from database.models.base import Base
from database.engine import get_engine, init_db, get_async_session
from database.session import AsyncSessionLocal
from database.repository import UserRepository, MessageRepository

__all__ = [
    "Base",
    "get_engine",
    "init_db",
    "get_async_session",
    "AsyncSessionLocal",
    "UserRepository",
    "MessageRepository",
]
