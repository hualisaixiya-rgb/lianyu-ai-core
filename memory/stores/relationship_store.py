"""Relationship Store。

管理关系层的所有数据：Metrics + Timeline + Promises（预留）。

设计原则：
- Timeline 是 Relationship 的子模块，不是新的 Memory 层
- Metrics 系统自动更新，LLM 只读
- Timeline 每天最多一条，由 LLM 在日期变更时生成
- 只加载最近 7 天 Timeline 注入 Prompt
"""

from dataclasses import dataclass
from datetime import datetime, date

from sqlalchemy import select, func as sql_func
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from database.models.relationship import RelationshipMetrics, TimelineEntry
from database.session import AsyncSessionLocal


# ================================================================
# Metrics（关系指标）
# ================================================================

@dataclass
class MetricsData:
    """关系指标的内存表示。"""
    first_chat_at: str = ""
    last_chat_at: str = ""
    total_chats: int = 0
    consecutive_days: int = 1
    bond_level: int = 1


class MetricsStore:
    """关系指标 CRUD。系统自动更新。"""

    async def get(
        self, platform: str, platform_user_id: str
    ) -> MetricsData | None:
        """获取关系指标。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(RelationshipMetrics).where(
                RelationshipMetrics.platform == platform,
                RelationshipMetrics.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return MetricsData(
                first_chat_at=row.first_chat_at.strftime("%Y-%m-%d") if row.first_chat_at else "",
                last_chat_at=row.last_chat_at.strftime("%Y-%m-%d %H:%M") if row.last_chat_at else "",
                total_chats=row.total_chats,
                consecutive_days=row.consecutive_days,
                bond_level=row.bond_level,
            )

    async def touch(
        self, platform: str, platform_user_id: str
    ) -> None:
        """每次对话时更新指标。自动处理首次记录/连续天数。"""
        now = datetime.now()
        today = now.date()

        async with AsyncSessionLocal.get_session() as session:
            stmt = select(RelationshipMetrics).where(
                RelationshipMetrics.platform == platform,
                RelationshipMetrics.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                row = RelationshipMetrics(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    first_chat_at=now,
                    last_chat_at=now,
                    total_chats=1,
                    consecutive_days=1,
                )
                session.add(row)
                logger.debug(f"Metrics 新建: [{platform}:{platform_user_id}]")
            else:
                row.total_chats += 1
                row.last_chat_at = now

                # 连续天数
                if row.last_chat_at:
                    last_date = row.last_chat_at.date()
                    if last_date == today - date.timedelta(days=1):
                        row.consecutive_days += 1
                    elif last_date < today - date.timedelta(days=1):
                        row.consecutive_days = 1

                # bond_level 暂不自动增长，保持手动或未来规则驱动


# ================================================================
# Timeline（共同经历时间线）
# ================================================================

# Timeline 注入上限
MAX_TIMELINE_DAYS = 7

# Timeline 生成 Prompt（结构化提取）
TIMELINE_PROMPT = """\
从以下对话摘要中提取今天的关系事件。

返回 JSON：
{
  "summary": "一段话总结今天对方经历了什么、AI 如何回应（不超过100字）",
  "emotion": "对方的主要情绪（平静/开心/疲惫/难过/焦虑/其他）",
  "relationship_meaning": "今天的互动对这段关系意味着什么（不超过30字，没有就写空字符串）",
  "topic": "相关主题标签（如：排练/身份确认/日常陪伴）",
  "importance": 5
}

规则：
- summary 主语是"对方"，不是"你们"。描述对方做了什么、说了什么，然后 AI 如何回应。
  正确："对方排练了一整天很疲惫，AI 陪伴聊天。"
  错误："你们一起排练了一整天。"
- 不要把 AI 的陪伴性语言（"我陪你""我在呢"）转成共同经历。
- 不要把 AI 的虚拟表达（"我陪你去"）写成事实。
- importance: 1-3=普通日常, 4-6=有意义的互动, 7-8=重要关系时刻, 9-10=极少使用
"""


class TimelineStore:
    """共同经历时间线 CRUD。"""

    async def get_recent(
        self, platform: str, platform_user_id: str, days: int = MAX_TIMELINE_DAYS
    ) -> list[dict]:
        """获取最近 N 天的 Timeline，按日期降序。

        Returns:
            [{"date": "...", "summary": "...", "emotion": "...", "importance": N, ...}, ...]
        """
        async with AsyncSessionLocal.get_session() as session:
            stmt = (
                select(TimelineEntry)
                .where(
                    TimelineEntry.platform == platform,
                    TimelineEntry.platform_user_id == platform_user_id,
                )
                .order_by(TimelineEntry.date.desc())
                .limit(days)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "date": r.date,
                    "summary": r.summary,
                    "emotion": r.emotion or "",
                    "relationship_meaning": r.relationship_meaning or "",
                    "topic": r.topic or "",
                    "importance": r.importance,
                }
                for r in rows
            ]

    async def has_today(self, platform: str, platform_user_id: str) -> bool:
        """检查今天是否已有 Timeline 记录。"""
        today_str = date.today().isoformat()
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(sql_func.count()).select_from(TimelineEntry).where(
                TimelineEntry.platform == platform,
                TimelineEntry.platform_user_id == platform_user_id,
                TimelineEntry.date == today_str,
            )
            result = await session.execute(stmt)
            count = result.scalar_one()
            return count > 0

    async def add(
        self,
        platform: str,
        platform_user_id: str,
        date_str: str,
        summary: str,
        importance: int = 5,
    ) -> None:
        """添加一条 Timeline。同一天已有则更新。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            date_str: 日期 "2026-07-07"
            summary: 共同经历摘要
            importance: 重要性 1-10
        """
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(TimelineEntry).where(
                TimelineEntry.platform == platform,
                TimelineEntry.platform_user_id == platform_user_id,
                TimelineEntry.date == date_str,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.summary = summary
                existing.importance = importance
                logger.debug(f"Timeline 更新: [{platform}:{platform_user_id}] {date_str}")
            else:
                entry = TimelineEntry(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    date=date_str,
                    summary=summary,
                    importance=importance,
                )
                session.add(entry)
                logger.info(f"Timeline 新增: [{platform}:{platform_user_id}] {date_str}")

    async def generate_and_store(
        self,
        platform: str,
        platform_user_id: str,
        date_str: str,
        conversation_summary: str,
        provider,  # OpenAICompatibleProvider
    ) -> dict | None:
        """生成今日 Timeline 并存储（V3 结构化升级）。

        返回生成的 Timeline 条目 dict，包含 summary/emotion/relationship_meaning/topic/importance。
        """
        if not conversation_summary or len(conversation_summary) < 20:
            logger.debug(f"对话摘要太短，跳过 Timeline 生成: {date_str}")
            return None

        try:
            raw = await provider.chat(
                messages=[{"role": "user", "content": (
                    f"今天的对话摘要：\n{conversation_summary}"
                )}],
                system_prompt=TIMELINE_PROMPT,
            )
            text = raw.strip()

            # 解析 JSON
            import json
            if "```" in text:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    text = text[start:end]

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                # 兼容纯文本格式
                data = {"summary": text[:200]}

            summary = data.get("summary", "")
            if not summary or len(summary) < 10:
                return None

            emotion = data.get("emotion", "")
            relationship_meaning = data.get("relationship_meaning", "")
            topic = data.get("topic", "")
            importance = data.get("importance", 5)

            await self._add_full(
                platform, platform_user_id, date_str,
                summary, emotion, relationship_meaning, topic, importance,
            )
            logger.info(f"Timeline 生成: [{platform}:{platform_user_id}] {date_str} importance={importance}")
            try:
                from archive.memory_archive import record as mem_record
                mem_record("create", "timeline", summary[:100],
                           "summarizer", importance,
                           platform=platform, user_id=platform_user_id)
            except Exception:
                pass
            return {
                "summary": summary,
                "emotion": emotion,
                "relationship_meaning": relationship_meaning,
                "topic": topic,
                "importance": importance,
            }
        except Exception as e:
            logger.warning(f"Timeline 生成失败: {e}")
            return None

    async def _add_full(
        self,
        platform: str,
        platform_user_id: str,
        date_str: str,
        summary: str,
        emotion: str = "",
        relationship_meaning: str = "",
        topic: str = "",
        importance: int = 5,
    ) -> None:
        """添加一条完整的 Timeline 条目（含结构化字段）。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = select(TimelineEntry).where(
                TimelineEntry.platform == platform,
                TimelineEntry.platform_user_id == platform_user_id,
                TimelineEntry.date == date_str,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.summary = summary
                existing.importance = importance
                existing.emotion = emotion
                existing.relationship_meaning = relationship_meaning
                existing.topic = topic
                logger.debug(f"Timeline 更新: [{platform}:{platform_user_id}] {date_str}")
            else:
                entry = TimelineEntry(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    date=date_str,
                    summary=summary,
                    importance=importance,
                    emotion=emotion,
                    relationship_meaning=relationship_meaning,
                    topic=topic,
                )
                session.add(entry)
                logger.info(f"Timeline 新增: [{platform}:{platform_user_id}] {date_str}")

    # ================================================================
    # 格式化
    # ================================================================

    @staticmethod
    def format_for_prompt(entries: list[dict]) -> str:
        """将 Timeline 格式化为 Prompt 注入文本（V3 升级）。"""
        if not entries:
            return ""

        lines = ["【最近关系事件】"]

        for entry in entries[:MAX_TIMELINE_DAYS]:
            date_short = entry["date"][-5:]  # "07-07"
            line = f"- {date_short}: {entry['summary']}"
            if entry.get("emotion"):
                line += f"（情绪：{entry['emotion']}）"
            lines.append(line)

        return "\n".join(lines)


# ================================================================
# RelationshipStore（聚合入口）
# ================================================================

class RelationshipStore:
    """关系层聚合入口。

    组合 Metrics + Timeline，提供统一接口。
    """

    def __init__(self) -> None:
        self.metrics = MetricsStore()
        self.timeline = TimelineStore()
        logger.info("RelationshipStore 初始化完成")

    async def touch(self, platform: str, platform_user_id: str) -> None:
        """更新关系指标（每次对话调用）。"""
        await self.metrics.touch(platform, platform_user_id)

    async def get_timeline_context(
        self, platform: str, platform_user_id: str
    ) -> str:
        """获取 Timeline Prompt 上下文。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID

        Returns:
            格式化的 Timeline Prompt 文本
        """
        entries = await self.timeline.get_recent(platform, platform_user_id)
        return self.timeline.format_for_prompt(entries)

    async def generate_timeline_if_needed(
        self,
        platform: str,
        platform_user_id: str,
        conversation_summary: str,
        provider,
    ) -> None:
        """如果今天还没有 Timeline，尝试生成。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            conversation_summary: 对话摘要
            provider: LLM Provider
        """
        if await self.timeline.has_today(platform, platform_user_id):
            return

        today_str = date.today().isoformat()
        await self.timeline.generate_and_store(
            platform, platform_user_id, today_str, conversation_summary, provider,
        )
