"""Memory Consolidator —— 记忆整理管道。

负责：
1. 从 relationship_timeline 中提炼 RelationshipMemory
2. 去重：相似理解更新而非新增
3. 衰减管理：定期降低 decay_score

管道：
  messages → summarizer → timeline → consolidator → relationship_memory

原则：
- 不直接从单次聊天生成关系理解
- 来源必须经过 relationship_timeline
- 只在满足生成守卫条件时才生成
"""

from datetime import datetime, date

from loguru import logger

from memory.stores.relationship_memory_store import (
    RelationshipMemoryStore,
    can_generate_from_timeline,
)


# 提炼 Prompt（极简，~80 tokens）
CONSOLIDATION_PROMPT = """\
从以下共同经历中提炼一条关于"这段关系"的理解。

规则：
- 聚焦于用户在这段关系中表现出的需要、模式、边界
- 不是总结事件，是理解关系
- 用一句话表达
- 如果没有值得提炼的关系理解，返回空

输出格式（JSON）：
{"category":"understanding|pattern|need|boundary","content":"一句话关系理解","importance":5,"confidence":5}
"""


class MemoryConsolidator:
    """记忆整理器。

    从 Timeline 中提炼 RelationshipMemory。

    使用方式：
        consolidator = MemoryConsolidator(rel_memory_store)
        count = await consolidator.consolidate(platform, uid, timeline_entries, provider)
    """

    def __init__(
        self,
        rel_memory_store: RelationshipMemoryStore | None = None,
    ) -> None:
        self.rel_memory = rel_memory_store or RelationshipMemoryStore()

    async def consolidate(
        self,
        platform: str,
        platform_user_id: str,
        timeline_entries: list[dict],
        provider,  # OpenAICompatibleProvider
    ) -> int:
        """从 Timeline 条目中提炼关系理解。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            timeline_entries: 最近的 Timeline 条目
            provider: LLM Provider

        Returns:
            本次新增/更新的关系理解条数
        """
        if not timeline_entries:
            return 0

        # 获取已有数量
        existing = await self.rel_memory.get_recent(
            platform, platform_user_id, limit=10
        )
        existing_count = len(existing)

        generated = 0
        for entry in timeline_entries:
            # 守卫：是否满足生成条件
            if not can_generate_from_timeline(entry, existing_count):
                continue

            # 提炼
            try:
                result = await self._consolidate_one(entry, provider)
                if result and result.get("content"):
                    await self.rel_memory.add(
                        platform=platform,
                        platform_user_id=platform_user_id,
                        content=result["content"],
                        category=result.get("category", ""),
                        evidence=entry.get("summary", "")[:200],
                        importance=result.get("importance", 5),
                        confidence=result.get("confidence", 5),
                    )
                    generated += 1
            except Exception as e:
                logger.warning(f"Consolidator 提炼失败: {e}")

        if generated > 0:
            logger.info(
                f"Consolidator: [{platform}:{platform_user_id}] "
                f"+{generated} 条关系理解"
            )

        return generated

    async def _consolidate_one(
        self, entry: dict, provider
    ) -> dict | None:
        """从一条 Timeline 提炼一条关系理解。"""
        import json

        summary = entry.get("summary", "")
        if len(summary) < 15:
            return None

        try:
            raw = await provider.chat(
                messages=[{"role": "user", "content": (
                    f"共同经历：\n{summary}\n\n"
                    "提炼一条关于这段关系的理解。"
                )}],
                system_prompt=CONSOLIDATION_PROMPT,
            )
            text = raw.strip()

            # 解析 JSON
            if "```" in text:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    text = text[start:end]

            data = json.loads(text)
            if isinstance(data, dict) and data.get("content"):
                return {
                    "category": data.get("category", ""),
                    "content": data["content"],
                    "importance": min(max(data.get("importance", 5), 1), 10),
                    "confidence": min(max(data.get("confidence", 5), 1), 10),
                }
        except Exception:
            pass
        return None

    async def daily_maintenance(
        self, platform: str, platform_user_id: str
    ) -> None:
        """每日维护：应用衰减。"""
        kept = await self.rel_memory.apply_decay(platform, platform_user_id)
        if kept > 0:
            logger.debug(
                f"Consolidator maintenance: [{platform}:{platform_user_id}] "
                f"{kept} 条关系理解存活"
            )
