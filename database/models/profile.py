"""用户画像 ORM 模型。

独立的 user_profiles 表，Key-Value 字段设计。
Profile 不参与模糊搜索，始终按 platform + platform_user_id 精确读取。

设计原则：
- 每个 (platform, platform_user_id) 只有一条记录
- 字段可为 NULL（未设置）
- likes/dislikes 存储为 JSON 字符串列表
- 支持增量更新：只更新有值的字段
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from database.models.base import Base


class UserProfile(Base):
    """用户画像表。

    存储用户的身份信息、偏好等结构化数据。
    每条记录对应一个平台的唯一用户。
    """

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    platform_user_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )

    # ================================================================
    # 身份信息 (Identity)
    # ================================================================
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """姓名"""

    nickname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    """昵称／称呼偏好"""

    birthday: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """生日（格式化字符串，如 "2000-01-15"）"""

    school: Mapped[str | None] = mapped_column(String(256), nullable=True)
    """学校"""

    major: Mapped[str | None] = mapped_column(String(256), nullable=True)
    """专业"""

    job: Mapped[str | None] = mapped_column(String(256), nullable=True)
    """工作／职业"""

    # ================================================================
    # 偏好 (Preferences)
    # ================================================================
    likes: Mapped[str | None] = mapped_column(Text, nullable=True)
    """喜欢的事物（JSON 字符串数组，如 '["猫","雨天","拉面"]'）"""

    dislikes: Mapped[str | None] = mapped_column(Text, nullable=True)
    """不喜欢的事物（JSON 字符串数组）"""

    # ================================================================
    # 元数据
    # ================================================================
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
