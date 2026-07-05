"""Agent 状态持久化。

存储每个用户的 bond（关系值）、emotion（情绪）、
最后活跃时间、最后发送时间等。
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base
from database.session import AsyncSessionLocal
from loguru import logger

from sqlalchemy import select


class AgentState(Base):
    """Agent 状态表 —— 每个用户一行。

    Attributes:
        platform / platform_user_id: 用户标识
        bond: 关系值 0.0~1.0，默认 0.2
        emotion: 情绪状态 calm / neutral / soft_warm
        last_user_active_time: 用户最后活跃时间
        last_bot_message_time: Bot 最后主动发消息时间
        daily_message_count: 今日已发送主动消息数
        daily_reset_date: 今日计数重置日期
    """

    __tablename__ = "agent_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False)

    bond: Mapped[float] = mapped_column(Float, default=0.2, nullable=False)
    emotion: Mapped[str] = mapped_column(String(32), default="calm", nullable=False)

    last_user_active_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_bot_message_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    daily_message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_reset_date: Mapped[str] = mapped_column(
        String(10), server_default=text("date('now')"), nullable=False
    )


class AgentStateRepository:
    """Agent 状态仓库。"""

    # 每日消息上限
    DAILY_MAX = 5

    # 冷却时间（分钟）
    COOLDOWN_MINUTES = 30

    @staticmethod
    async def get_or_create(platform: str, platform_user_id: str) -> AgentState:
        """获取或创建 Agent 状态。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(AgentState).where(
                AgentState.platform == platform,
                AgentState.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            state = result.scalar_one_or_none()

            if not state:
                state = AgentState(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    bond=0.2,
                    emotion="calm",
                )
                session.add(state)
                await session.flush()
                logger.debug(f"AgentState 创建: {platform}:{platform_user_id}")

            return state

    @staticmethod
    async def update_user_active(platform: str, platform_user_id: str) -> None:
        """更新用户最后活跃时间并微增 bond。"""
        state = await AgentStateRepository.get_or_create(platform, platform_user_id)
        async with AsyncSessionLocal.get_session() as session:
            state = await session.merge(state)
            state.last_user_active_time = func.now()
            state.bond = min(1.0, state.bond + 0.01)
            await session.flush()

    @staticmethod
    async def record_sent(platform: str, platform_user_id: str) -> None:
        """记录一次主动消息发送。更新发送时间、每日计数、重置 bond 微减。"""
        state = await AgentStateRepository.get_or_create(platform, platform_user_id)
        async with AsyncSessionLocal.get_session() as session:
            state = await session.merge(state)
            state.last_bot_message_time = func.now()
            # 重置每日计数（跨天）
            today = datetime.now().strftime("%Y-%m-%d")
            if state.daily_reset_date != today:
                state.daily_reset_date = today
                state.daily_message_count = 0
            state.daily_message_count += 1
            state.bond = max(0.0, state.bond - 0.005)
            await session.flush()

    @staticmethod
    async def decay_bond_for_inactive(
        platform: str, platform_user_id: str, hours_inactive: float
    ) -> None:
        """长时间不互动，bond 轻微衰减。"""
        if hours_inactive < 24:
            return
        state = await AgentStateRepository.get_or_create(platform, platform_user_id)
        async with AsyncSessionLocal.get_session() as session:
            state = await session.merge(state)
            decay = min(0.05, (hours_inactive - 24) * 0.001)
            state.bond = max(0.05, state.bond - decay)
            await session.flush()
