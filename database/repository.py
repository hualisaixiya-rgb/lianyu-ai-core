"""数据库仓库层。

封装数据库的增删改查操作，为 AI Core 提供简洁的接口。
遵循 Repository 模式，将 SQL 细节与业务逻辑分离。
"""

from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.message import Message
from database.models.user import User
from database.session import AsyncSessionLocal
from loguru import logger


class UserRepository:
    """用户仓库。

    负责用户的注册和查询。
    """

    @staticmethod
    async def get_or_create(
        platform: str,
        platform_user_id: str,
        username: str | None = None,
    ) -> User:
        """获取或创建用户。

        如果用户已存在，更新用户名和最后交互时间。
        如果不存在，创建新用户。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            username: 用户昵称

        Returns:
            User 实例
        """
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(User).where(
                User.platform == platform,
                User.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user:
                # 更新用户名和最后交互时间
                if username and username != user.username:
                    user.username = username
                user.updated_at = func.now()
                logger.debug(f"用户已存在: {platform}:{platform_user_id}")
            else:
                user = User(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    username=username,
                )
                session.add(user)
                await session.flush()
                logger.info(f"新用户注册: {platform}:{platform_user_id} ({username})")

            return user

    @staticmethod
    async def get_all_users() -> list[User]:
        """获取所有注册用户。

        Returns:
            User 列表
        """
        from sqlalchemy import select
        from database.models.user import User as U
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(U)
            result = await session.execute(stmt)
            return list(result.scalars().all())


class MessageRepository:
    """消息仓库。

    负责消息的存储和查询。
    """

    @staticmethod
    async def save(
        platform: str,
        platform_user_id: str,
        role: str,
        content: str,
    ) -> Message:
        """保存一条消息。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            role: 消息角色（"user" / "assistant"）
            content: 消息内容

        Returns:
            保存后的 Message 实例
        """
        async with AsyncSessionLocal.get_session() as session:
            msg = Message(
                platform=platform,
                platform_user_id=platform_user_id,
                role=role,
                content=content,
            )
            session.add(msg)
            await session.flush()
            logger.debug(f"消息已保存: [{role}] {content[:30]}...")
            return msg

    @staticmethod
    async def get_recent_history(
        platform: str,
        platform_user_id: str,
        limit: int = 50,
    ) -> list[dict[str, str]]:
        """获取用户最近的对话历史。

        按时间正序返回，用于发送给 LLM 作为上下文。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            limit: 返回最近多少条消息

        Returns:
            消息列表，格式 [{"role": "user", "content": "..."}, ...]
        """
        async with AsyncSessionLocal.get_session() as session:
            # 先查最新的 N 条（按时间倒序），再反转成正序
            stmt = (
                select(Message)
                .where(
                    Message.platform == platform,
                    Message.platform_user_id == platform_user_id,
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

            # 反转：时间正序
            records.reverse()

            return [
                {"role": r.role, "content": r.content}
                for r in records
            ]

    @staticmethod
    async def count_messages(
        platform: str,
        platform_user_id: str,
    ) -> int:
        """统计用户消息数。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID

        Returns:
            消息总数
        """
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(func.count()).where(
                Message.platform == platform,
                Message.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            return result.scalar_one()
