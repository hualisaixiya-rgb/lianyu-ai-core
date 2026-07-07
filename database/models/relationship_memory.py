"""Relationship Memory ORM 模型。

存储长期关系理解——不是用户事实，不是共同事件，
而是"这段关系的模式、需要、边界"。

与 memory_records 的区别：
- memory_records: "用户叫夏离萤"（事实）
- relationship_memories: "被记住对用户很重要"（关系理解）

生成约束：
- 来源必须经过 relationship_timeline
- timeline importance >= 7 或用户明确表达长期偏好 或重复出现相同模式
- 不直接从单次聊天生成
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class RelationshipMemory(Base):
    """长期关系理解表。

    存储对"这段关系"的理解，而非用户事实。
    每一条都是对关系模式的抽象。
    """

    __tablename__ = "relationship_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )

    # ---- 内容 ----
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    """分类：understanding / pattern / need / boundary"""

    content: Mapped[str] = mapped_column(Text, nullable=False)
    """关系理解内容。如"被记住对用户很重要，用户曾多次确认" """

    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    """支撑这条理解的 Timeline 来源（日期列表或摘要）"""

    # ---- 评分 ----
    importance: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    """重要程度 1-10"""

    confidence: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    """可信程度 1-10。越高越确定"""

    # ---- 生命周期 ----
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    """最后一次被新证据确认的时间"""

    decay_score: Mapped[float] = mapped_column(
        Integer, default=100, nullable=False
    )
    """衰减分数 0-100。未被重新确认时会降低。100=最新, 0=已淘汰"""

    # ---- 元数据 ----
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
