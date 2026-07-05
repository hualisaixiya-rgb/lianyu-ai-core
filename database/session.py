"""数据库会话上下文管理器。

提供 AsyncSession 的生命周期管理。
"""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from database.engine import get_async_session


class AsyncSessionLocal:
    """异步会话本地管理类。

    提供静态方法以兼容 python-telegram-bot 的回调风格。
    """

    @staticmethod
    @asynccontextmanager
    async def get_session():
        """获取一个数据库会话的异步上下文管理器。

        自动处理 commit/rollback，确保会话正确关闭。

        Yields:
            AsyncSession: 数据库会话实例
        """
        async_session = get_async_session()
        async with async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
