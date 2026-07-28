"""Relationship Growth Engine — V3.1 轻量版。

三大能力：
1. Pattern Discovery — 从 Timeline 中发现重复模式
2. Memory Merge — 合并冗余关系理解
3. Emotion Trend — 多日情绪趋势

触发条件：Timeline 新增 >= 5 条。
"""

import json
from datetime import datetime

from loguru import logger

from memory.stores.relationship_memory_store import RelationshipMemoryStore


# Pattern Discovery Prompt
PATTERN_PROMPT = """\
从以下最近几天的共同经历中，发现一个重复出现的模式。

规则：
- 聚焦于"用户在这段关系中反复表现出的行为或需要"
- 不是总结事件，是发现规律
- 如果没有明显模式，返回空

输出格式（JSON）：
{"content":"一句话描述模式","category":"pattern","importance":5}
"""

# Merge Prompt
MERGE_PROMPT = """\
以下是多条关于"这段关系"的理解。请合并意思相似或重复的条目。

规则：
- 合并后不超过 3 条
- 保留最重要、最有信息量的
- 合并后的内容应比原来更凝练

输出格式（JSON）：
[{"content":"合并后的内容","category":"pattern|need|understanding","importance":5}]
"""


class RelationshipGrowth:
    """关系成长引擎。"""

    def __init__(self, rel_store: RelationshipMemoryStore | None = None):
        self.store = rel_store or RelationshipMemoryStore()

    async def run_growth_cycle(
        self,
        platform: str,
        platform_user_id: str,
        timeline_entries: list[dict],
        provider,
    ) -> dict:
        """执行一次 Growth Cycle（后台异步，不阻塞回复）。

        Returns:
            {"patterns": N, "merged": N}
        """
        result = {"patterns": 0, "merged": 0}

        if len(timeline_entries) < 3:
            return result

        # 1. Pattern Discovery
        try:
            pattern = await self._discover_pattern(timeline_entries, provider)
            if pattern:
                await self.store.add(
                    platform, platform_user_id,
                    content=pattern["content"],
                    category=pattern.get("category", "pattern"),
                    importance=pattern.get("importance", 5),
                    confidence=5,
                    evidence="pattern: " + ", ".join(
                        e.get("date", "")[:5] for e in timeline_entries[:5]
                    ),
                )
                result["patterns"] = 1
                logger.info(
                    f"Growth Pattern: [{platform}:{platform_user_id}] "
                    f"{pattern['content'][:60]}..."
                )
        except Exception as e:
            logger.warning(f"Pattern discovery 失败: {e}")

        # 2. Memory Merge（如果 > 10 条）
        try:
            existing = await self.store.get_recent(platform, platform_user_id, limit=50)
            if len(existing) > 10:
                merged_count = await self._merge_if_needed(
                    platform, platform_user_id, existing, provider,
                )
                result["merged"] = merged_count
        except Exception as e:
            logger.warning(f"Memory merge 失败: {e}")

        return result

    async def _discover_pattern(
        self, entries: list[dict], provider
    ) -> dict | None:
        """从 Timeline 中发现模式。"""
        summaries = "\n".join(
            f"- {e.get('date', '')}: {e.get('summary', '')[:80]}"
            for e in entries[:10]
        )
        raw = await provider.chat(
            messages=[{"role": "user", "content": f"最近经历：\n{summaries}"}],
            system_prompt=PATTERN_PROMPT,
        )
        text = raw.strip()
        if "{" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            text = text[start:end]
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("content"):
                return data
        except json.JSONDecodeError:
            pass
        return None

    async def _merge_if_needed(
        self,
        platform: str,
        platform_user_id: str,
        entries: list[dict],
        provider,
    ) -> int:
        """合并冗余记忆。"""
        contents = "\n".join(
            f"- [{e.get('category', '')}] {e['content']}"
            for e in entries
        )
        raw = await provider.chat(
            messages=[{"role": "user", "content": f"需合并的条目：\n{contents}"}],
            system_prompt=MERGE_PROMPT,
        )
        text = raw.strip()
        if "[" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            text = text[start:end]
        try:
            merged = json.loads(text)
            if isinstance(merged, list) and len(merged) > 0:
                # 标记旧条为合并
                for e in entries:
                    try:
                        await self.store.mark_merged(
                            platform, platform_user_id, e["content"]
                        )
                    except Exception:
                        pass
                # 写入合并后的新条目
                for item in merged[:3]:
                    if item.get("content"):
                        await self.store.add(
                            platform, platform_user_id,
                            content=item["content"],
                            category=item.get("category", "pattern"),
                            importance=item.get("importance", 5),
                            confidence=5,
                        )
                return len(merged)
        except json.JSONDecodeError:
            pass
        return 0


def get_emotion_trend(timeline_entries: list[dict]) -> str:
    """从最近 Timeline 中提取情绪趋势（纯规则，零 Token）。

    V3.5: 从要求 3/3 完全一致 → ≥2/3 一致即触发。
    """
    if len(timeline_entries) < 3:
        return ""

    recent = timeline_entries[:3]
    emotions = [e.get("emotion", "") for e in recent if e.get("emotion")]
    if len(emotions) < 3:
        return ""

    # V3.5: ≥2/3 一致即触发
    from collections import Counter
    most_common = Counter(emotions).most_common(1)[0]
    if most_common[1] >= 2:
        emotion = most_common[0]
        trend_map = {
            "疲惫": "最近对方似乎一直比较疲惫。请降低说教，增加陪伴。",
            "开心": "最近对方心情不错。可以更轻松地聊天。",
            "难过": "最近对方情绪不太好。多一些安静陪伴，少一些追问。",
            "焦虑": "最近对方比较焦虑。保持稳定、温柔的语气。",
        }
        return trend_map.get(emotion, "")

    return ""
