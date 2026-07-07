"""用户画像存储。

ProfileStore 负责 user_profiles 表的 CRUD 操作。
设计为 Key-Value 精确读写，不参与模糊搜索。

设计原则：
- 每个 (platform, platform_user_id) 一条记录，upsert 语义
- 增量更新：只更新有值的字段，不清空已有数据
- format_for_prompt() 将 Profile 转为 LLM 可读的文本
"""

import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from database.models.profile import UserProfile
from database.session import AsyncSessionLocal


# Profile 中有意义的字段（排除 id / platform / platform_user_id / created_at / updated_at）
PROFILE_FIELDS = [
    "name",
    "nickname",
    "birthday",
    "school",
    "major",
    "job",
    "likes",
    "dislikes",
]

# 字段 → 中文标签映射
FIELD_LABELS: dict[str, str] = {
    "name": "姓名",
    "nickname": "昵称",
    "birthday": "生日",
    "school": "学校",
    "major": "专业",
    "job": "工作",
    "likes": "喜欢",
    "dislikes": "不喜欢",
}


@dataclass
class ProfileData:
    """用户画像的内存表示。

    与 ORM 模型解耦，方便后续切换到其他存储后端。
    """

    platform: str = ""
    platform_user_id: str = ""
    name: str | None = None
    nickname: str | None = None
    birthday: str | None = None
    school: str | None = None
    major: str | None = None
    job: str | None = None
    likes: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转为字典（排除平台标识）。"""
        return {
            "name": self.name,
            "nickname": self.nickname,
            "birthday": self.birthday,
            "school": self.school,
            "major": self.major,
            "job": self.job,
            "likes": json.dumps(self.likes, ensure_ascii=False) if self.likes else None,
            "dislikes": json.dumps(self.dislikes, ensure_ascii=False) if self.dislikes else None,
        }

    def get_field(self, field_name: str) -> Any:
        """按名称读取字段值。"""
        if field_name == "likes":
            return self.likes
        if field_name == "dislikes":
            return self.dislikes
        return getattr(self, field_name, None)

    def has_any_data(self) -> bool:
        """是否有任何非空字段。"""
        return any(
            self.get_field(f) for f in PROFILE_FIELDS
        )


class ProfileStore:
    """用户画像存储。

    基于 SQLAlchemy + SQLite 实现。
    提供精确的 Key-Value 读写接口。

    使用方式：
        store = ProfileStore()
        await store.upsert("telegram", "12345", name="夏离萤")
        profile = await store.get("telegram", "12345")
        text = store.format_for_prompt(profile)
    """

    # ================================================================
    # 读操作
    # ================================================================

    async def get(self, platform: str, platform_user_id: str) -> ProfileData | None:
        """获取用户画像。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID

        Returns:
            ProfileData 或 None（用户不存在）
        """
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(UserProfile).where(
                UserProfile.platform == platform,
                UserProfile.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return None

            return self._row_to_data(row)

    async def get_field(
        self, platform: str, platform_user_id: str, field_name: str
    ) -> Any:
        """读取单个 Profile 字段。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            field_name: 字段名（如 "name", "likes"）

        Returns:
            字段值，不存在返回 None
        """
        profile = await self.get(platform, platform_user_id)
        if profile is None:
            return None
        return profile.get_field(field_name)

    # ================================================================
    # 写操作
    # ================================================================

    async def upsert(
        self,
        platform: str,
        platform_user_id: str,
        **fields: Any,
    ) -> None:
        """创建或更新用户画像（增量更新）。

        只更新有值的字段，不清空已有数据。
        例如：
            upsert("tg", "1", name="夏离萤")
            upsert("tg", "1", birthday="2000-01-15")  # name 不会被覆盖

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            **fields: 要更新的字段，支持 likes/dislikes 传 list
        """
        # 序列化列表字段
        updates: dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key in ("likes", "dislikes") and isinstance(value, list):
                updates[key] = json.dumps(value, ensure_ascii=False)
            elif key in PROFILE_FIELDS:
                updates[key] = value

        if not updates:
            return

        async with AsyncSessionLocal.get_session() as session:
            stmt = select(UserProfile).where(
                UserProfile.platform == platform,
                UserProfile.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                # 新建
                row = UserProfile(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    **updates,
                )
                session.add(row)
                logger.info(
                    f"Profile 新建: [{platform}:{platform_user_id}] "
                    f"fields={list(updates.keys())}"
                )
            else:
                # 增量更新：只覆盖有值的字段
                changed = False
                for key, value in updates.items():
                    current = getattr(row, key, None)
                    if current != value:
                        setattr(row, key, value)
                        changed = True
                if changed:
                    logger.info(
                        f"Profile 更新: [{platform}:{platform_user_id}] "
                        f"fields={list(updates.keys())}"
                    )

    # ================================================================
    # 格式化
    # ================================================================

    def format_for_prompt(self, profile: ProfileData | None) -> str:
        """完整版 Profile（等价于 format_full）。"""
        return self.format_full(profile)

    def format_full(self, profile: ProfileData | None) -> str:
        """完整版 Profile —— 身份确认时使用。

        输出所有有值的字段。
        """
        if profile is None or not profile.has_any_data():
            return ""

        lines = ["关于这个聊天对象，你知道："]
        for field_name in PROFILE_FIELDS:
            value = profile.get_field(field_name)
            if not value:
                continue
            label = FIELD_LABELS.get(field_name, field_name)
            if field_name in ("likes", "dislikes") and isinstance(value, list):
                lines.append(f"- {label}：{', '.join(value)}")
            else:
                lines.append(f"- {label}：{value}")
        return "\n".join(lines)

    def format_compact(self, profile: ProfileData | None) -> str:
        """精简版 Profile —— 日常聊天时使用。

        只输出姓名 + 最多 1 个其他字段。
        """
        if profile is None or not profile.has_any_data():
            return ""

        parts = []
        if profile.name:
            parts.append(f"姓名：{profile.name}")

        # 选一个最有信息量的额外字段
        for f in ["major", "school", "job", "nickname"]:
            v = profile.get_field(f)
            if v:
                parts.append(f"{FIELD_LABELS.get(f, f)}：{v}")
                break

        if not parts:
            return ""
        return "关于对方，你知道：" + "，".join(parts)

    def format_minimal(self, profile: ProfileData | None) -> str:
        """最小版 Profile —— 普通问候时使用。

        只输出姓名。不输出其他任何信息。
        """
        if profile is None or not profile.name:
            return ""
        return f"对方叫{profile.name}。"

    # ================================================================
    # 内部方法
    # ================================================================

    @staticmethod
    def _row_to_data(row: UserProfile) -> ProfileData:
        """将 ORM 行转为 ProfileData。"""
        likes = None
        if row.likes:
            try:
                likes = json.loads(row.likes)
            except json.JSONDecodeError:
                likes = [row.likes]

        dislikes = None
        if row.dislikes:
            try:
                dislikes = json.loads(row.dislikes)
            except json.JSONDecodeError:
                dislikes = [row.dislikes]

        return ProfileData(
            platform=row.platform,
            platform_user_id=row.platform_user_id,
            name=row.name,
            nickname=row.nickname,
            birthday=row.birthday,
            school=row.school,
            major=row.major,
            job=row.job,
            likes=likes or [],
            dislikes=dislikes or [],
        )
