"""记忆召回器。

负责在每次对话前召回相关信息，注入 System Prompt。

设计原则：
- Profile 是常驻上下文：每次请求都加载，不参与搜索
- LongMemory 是按需上下文：根据用户查询搜索相关记忆

这样"我是谁？"不需要 search("我是谁？") ——
Profile.name 已经在 Prompt 里了，LLM 直接能回答。
"""

from dataclasses import dataclass

from loguru import logger

from memory.base import MemoryStore
from memory.stores.profile_store import ProfileStore


@dataclass
class RetrieveResult:
    """召回结果。

    Attributes:
        profile_context: 用户画像文本（可直接注入 Prompt）
        memory_context: 长期记忆文本（可直接注入 Prompt）
    """

    profile_context: str = ""
    memory_context: str = ""


class MemoryRetriever:
    """记忆召回器。

    组合 ProfileStore 和 MemoryStore，
    提供统一的记忆召回接口。

    使用方式：
        retriever = MemoryRetriever(profile_store, memory_store)
        result = await retriever.retrieve("telegram", "12345", query="我是谁？")
        # result.profile_context → "关于这个聊天对象，你知道：\n- 姓名：夏离萤"
        # result.memory_context → "你对这个聊天对象的记忆：\n- ..."
    """

    def __init__(
        self,
        profile_store: ProfileStore,
        memory_store: MemoryStore,
    ) -> None:
        """初始化召回器。

        Args:
            profile_store: 用户画像存储
            memory_store: 长期记忆存储
        """
        self.profile_store = profile_store
        self.memory_store = memory_store

    async def retrieve(
        self,
        platform: str,
        platform_user_id: str,
        query: str | None = None,
        memory_top_k: int = 5,
    ) -> RetrieveResult:
        """召回与当前查询相关的所有记忆。

        Profile 始终加载。LongMemory 按查询搜索。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            query: 用户当前消息（用于搜索 LongMemory，为空则返回最近记忆）
            memory_top_k: LongMemory 召回数量上限

        Returns:
            RetrieveResult（含 profile_context 和 memory_context）
        """
        result = RetrieveResult()

        # ---- Profile：常驻加载 ----
        profile = await self.profile_store.get(platform, platform_user_id)
        result.profile_context = self.profile_store.format_for_prompt(profile)
        if result.profile_context:
            logger.debug(
                f"Profile 已加载: [{platform}:{platform_user_id}] "
                f"name={profile.name if profile else None}"
            )

        # ---- LongMemory：按需搜索 ----
        items = await self._search_or_list(
            platform, platform_user_id, query, memory_top_k
        )
        result.memory_context = self._format_memories(items)

        return result

    # ================================================================
    # 内部方法
    # ================================================================

    async def _search_or_list(
        self,
        platform: str,
        platform_user_id: str,
        query: str | None,
        top_k: int,
    ) -> list:
        """搜索记忆，无匹配时返回空（V3.5.1: 移除全量 fallback）。

        Args:
            query: 搜索查询（为 None 时直接返回全部）
            top_k: 返回数量上限

        Returns:
            排序后的 MemoryItem 列表。无匹配时为空列表。
        """
        if query:
            items = await self.memory_store.search(
                platform, platform_user_id, query, top_k
            )
            # V3.5.1: 不再 fallback 到 list_all。search 返回空 → 无相关记忆。
            if items:
                logger.debug(
                    f"Memory retrieval: query={query[:30]!r} "
                    f"matched={len(items)} injected={min(len(items), top_k)}"
                )
        else:
            items = await self.memory_store.list_all(
                platform, platform_user_id
            )
            items.sort(key=lambda x: x.importance, reverse=True)
            items = items[:top_k]

        return items

    @staticmethod
    def _format_memories(items: list) -> str:
        """格式化 LongMemory 列表为 Prompt 文本。

        Args:
            items: MemoryItem 列表

        Returns:
            格式化的记忆文本。无记忆则返回空字符串。
        """
        if not items:
            return ""

        lines = ["【长期记忆】（可信度低于已确认信息，来自之前对话的提取）"]
        for item in items:
            lines.append(f"- {item.value}")

        return "\n".join(lines)
