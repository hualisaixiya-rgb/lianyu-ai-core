"""用户模型。

存储与 Bot 交互的用户基本信息。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class User(Base):
    """用户表。

    Attributes:
        id: 自增主键
        platform: 平台标识（"telegram", "wechat", "web" 等）
        platform_user_id: 平台侧用户 ID
        username: 用户昵称
        created_at: 首次交互时间
        updated_at: 最近交互时间
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
