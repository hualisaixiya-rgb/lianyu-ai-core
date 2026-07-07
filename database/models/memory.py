"""长期记忆记录模型。

存储从对话中提取的关键信息，用于跨会话记忆。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class MemoryRecord(Base):
    """长期记忆表。

    储存压缩后的关键记忆条目。每个条目关联一个用户。

    Attributes:
        id: 自增主键
        platform: 平台标识
        platform_user_id: 平台侧用户 ID
        key: 记忆关键词（用于检索）
        value: 记忆内容
        importance: 重要性分数（1-10），用于排序和淘汰
        created_at: 记录时间
    """

    __tablename__ = "memory_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # ---- Memory Safety ----
    source: Mapped[str] = mapped_column(
        String(32), default="unknown", nullable=False, index=True
    )
    """来源类型：user_explicit / assistant_generated / system / unknown"""

    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    """证据：用户原话或系统记录。用于追溯。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
