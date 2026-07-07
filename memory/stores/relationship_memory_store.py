"""Relationship Memory Store。

存储长期关系理解——不是事实，不是事件，而是"这段关系的模式"。

生成约束：
- 来源必须经过 relationship_timeline
- timeline importance >= 7 或重复出现相同模式 或用户明确表达长期偏好
- 不直接从单次聊天生成

与 Profile / LongMemory / Timeline 的区别：
- Profile: "用户叫夏离萤"（身份事实）
- LongMemory: "用户养了橘猫"（生活事实）
- Timeline: "2026-07-07: 用户告诉了AI名字"（共同事件）
- RelationshipMemory: "被记住对用户很重要"（关系理解）
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, func as sql_func
from loguru import logger

from database.models.relationship_memory import RelationshipMemory
from database.session import AsyncSessionLocal


MAX_INJECT = 3          # 最多注入 3 条
MIN_CONFIDENCE = 3      # 最低可信度
DECAY_PER_DAY = 5       # 每天衰减分数


@dataclass
class RelationshipMemoryData:
    """关系理解的内存表示。"""
    category: str = ""
    content: str = ""
    importance: int = 5
    confidence: int = 5
    decay_score: int = 100


class RelationshipMemoryStore:
    """长期关系理解 CRUD。"""

    # ================================================================
    # 写操作
    # ================================================================

    async def add(
        self,
        platform: str,
        platform_user_id: str,
        content: str,
        category: str = "",
        evidence: str = "",
        importance: int = 5,
        confidence: int = 5,
    ) -> int | None:
        """添加一条关系理解。

        如果内容高度相似（前 30 字相同），更新已有记录而非新增。
        """
        async with AsyncSessionLocal.get_session() as session:
            # 去重：检查前 30 字
            stmt = select(RelationshipMemory).where(
                RelationshipMemory.platform == platform,
                RelationshipMemory.platform_user_id == platform_user_id,
                RelationshipMemory.content.like(f"{content[:30]}%"),
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.confidence = min(existing.confidence + 1, 10)
                existing.last_confirmed_at = datetime.now()
                existing.decay_score = 100
                existing.evidence = (
                    f"{existing.evidence or ''}; {evidence}" if evidence
                    else existing.evidence
                )[:500]
                logger.debug(
                    f"RelationshipMemory 确认: [{platform}:{platform_user_id}] "
                    f"confidence={existing.confidence}"
                )
                return existing.id
            else:
                entry = RelationshipMemory(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    category=category,
                    content=content,
                    evidence=evidence,
                    importance=importance,
                    confidence=confidence,
                )
                session.add(entry)
                await session.flush()
                logger.info(
                    f"RelationshipMemory 新增: [{platform}:{platform_user_id}] "
                    f"category={category} confidence={confidence}"
                )
                return entry.id

    # ================================================================
    # 读操作
    # ================================================================

    async def get_recent(
        self,
        platform: str,
        platform_user_id: str,
        limit: int = MAX_INJECT,
    ) -> list[dict]:
        """获取最近的关系理解，按 importance * confidence 排序。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = (
                select(RelationshipMemory)
                .where(
                    RelationshipMemory.platform == platform,
                    RelationshipMemory.platform_user_id == platform_user_id,
                    RelationshipMemory.confidence >= MIN_CONFIDENCE,
                )
                .order_by(
                    (RelationshipMemory.importance * RelationshipMemory.confidence).desc()
                )
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "category": r.category or "",
                    "content": r.content,
                    "importance": r.importance,
                    "confidence": r.confidence,
                }
                for r in rows
            ]

    # ================================================================
    # 生命周期
    # ================================================================

    async def apply_decay(
        self, platform: str, platform_user_id: str
    ) -> int:
        """对所有关系理解应用每日衰减。返回衰减后仍有效的条数。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(RelationshipMemory).where(
                RelationshipMemory.platform == platform,
                RelationshipMemory.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

            kept = 0
            for row in rows:
                row.decay_score = max(0, row.decay_score - DECAY_PER_DAY)
                if row.decay_score > 0:
                    kept += 1

            if rows:
                logger.debug(
                    f"RelationshipMemory decay: [{platform}:{platform_user_id}] "
                    f"{len(rows)} → {kept} kept"
                )
            return kept

    # ================================================================
    # 格式化
    # ================================================================

    @staticmethod
    def format_for_prompt(entries: list[dict]) -> str:
        """将关系理解格式化为 Prompt 注入文本。

        Args:
            entries: 最近的关系理解列表

        Returns:
            格式化的 Prompt 文本。无数据时返回空字符串。
        """
        if not entries:
            return ""

        lines = ["【长期关系理解】"]
        for entry in entries:
            lines.append(f"- {entry['content']}")

        return "\n".join(lines)


# ================================================================
# 生成守卫
# ================================================================

def can_generate_from_timeline(
    timeline_entry: dict,
    existing_count: int,
) -> bool:
    """判断是否可以从一条 Timeline 条目生成关系理解。

    条件（满足任一即可）：
    1. timeline importance >= 7
    2. 用户明确表达了长期偏好（内容包含"喜欢""希望""想要"等）
    3. 已有 >= 3 条相似模式的 Timeline（重复出现）

    Args:
        timeline_entry: Timeline 条目 {"summary": "...", "importance": N, "emotion": "..."}
        existing_count: 当前已有的关系理解数量

    Returns:
        是否可以生成
    """
    importance = timeline_entry.get("importance", 5)

    # 条件 1: 高重要性
    if importance >= 7:
        return True

    summary = timeline_entry.get("summary", "")

    # 条件 2: 明确表达长期偏好
    preference_keywords = [
        "喜欢", "不喜欢", "希望", "想要", "讨厌", "重要", "珍惜",
        "一直", "总是", "经常", "每次",
    ]
    if any(kw in summary for kw in preference_keywords):
        return True

    # 条件 3: 不轻易从低质量 Timeline 生成
    if existing_count >= 5:
        return False  # 已有足够理解，不轻易新增

    return False
