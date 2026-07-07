"""消息模型。

存储用户与 AI 之间的聊天消息。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class Message(Base):
    """消息表。

    记录每次对话的用户消息和 AI 回复。
    按 platform + platform_user_id 分组，按时间排序即可重建对话历史。

    Attributes:
        id: 自增主键
        platform: 平台标识
        platform_user_id: 平台侧用户 ID
        role: 消息角色（"user" / "assistant" / "system"）
        content: 消息内容
        created_at: 消息时间
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context_visible: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    """是否进入 LLM 上下文。身份声明类消息设为 False，数据库保留但不注入 Prompt。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
