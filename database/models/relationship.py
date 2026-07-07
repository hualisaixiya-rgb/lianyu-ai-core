"""Relationship ORM 模型。

关系层存储"我们"的数据 —— 不是用户一个人的事实，而是我们共同经历的事。

包含：
- RelationshipMetrics: 关系量化指标（认识多久、聊了多少天）
- TimelineEntry:     共同经历时间线（每天一条，记录我们一起经历了什么）

Promises（约定）预留，未来扩展。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class RelationshipMetrics(Base):
    """关系量化指标。

    每个 (platform, platform_user_id) 一条记录。
    系统自动更新，LLM 只读。
    """

    __tablename__ = "relationship_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )

    # ---- 时间 ----
    first_chat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """第一次聊天的日期时间"""

    last_chat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """最近一次聊天的日期时间"""

    # ---- 计数 ----
    total_chats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    """总对话轮数（send + receive 各算一轮）"""

    consecutive_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    """连续聊天天数"""

    # ---- 关系 ----
    bond_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    """亲密度 1-10。1=陌生人，5=熟人，8=亲近，10=非常亲近。
    预留，暂不自动增长。"""

    # ---- 元数据 ----
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TimelineEntry(Base):
    """共同经历时间线。

    每天一条记录。记录"我们"一起经历了什么。
    与 LongMemory 不同：这里的���语是"我们"，不是"用户"。

    只加载最近 7 天注入 Prompt，更早的保留在数据库作为存档。
    """

    __tablename__ = "relationship_timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )

    # ---- 内容 ----
    date: Mapped[str] = mapped_column(String(16), nullable=False)
    """日期，格式 "2026-07-07"。每天最多一条。"""

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    """当天共同经历摘要。<200 字。"""

    importance: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    """重要性 1-10。高光时刻标记为更高。预留。"""

    # ---- 元数据 ----
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
