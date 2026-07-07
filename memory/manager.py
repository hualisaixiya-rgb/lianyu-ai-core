"""记忆管理器 V2。

Memory Engine V2 核心组件，组合：
- ProfileStore（用户画像，常驻注入 Prompt）
- MemoryStore（LongMemory，按需搜索）
- MemoryExtractor（分类提取 Profile + LongMemory）
- MemoryRetriever（分类召回，Profile 常驻 + LongMemory 搜索）

设计原则：
- Profile 不参与搜索，直接 Key-Value 读写
- LongMemory 保留搜索，走原有路径
- 一次 LLM 调用完成两类提取
"""

import json

from loguru import logger

from memory.base import MemoryItem, MemoryStore
from memory.extractor import MemoryExtractor
from memory.retriever import MemoryRetriever
from memory.stores.profile_store import ProfileStore


class MemoryManager:
    """记忆管理器 V2。

    封装 ProfileStore + MemoryStore + Extractor + Retriever，
    提供业务级别的记忆操作。

    使用方式：
        store = SQLiteMemoryStore()
        profile_store = ProfileStore()
        manager = MemoryManager(store, profile_store=profile_store)

        # 召回（对话前）
        result = await manager.get_context(platform, uid, query)
        # result.profile_context → "关于这个聊天对象，你知道：\n- 姓名：夏离萤"
        # result.memory_context → "你对这个聊天对象的记忆：\n- 用户养了一只猫"

        # 提取（对话后）
        await manager.extract_and_store(platform, uid, user_msg, ai_reply, provider)
    """

    def __init__(
        self,
        store: MemoryStore,
        profile_store: ProfileStore | None = None,
    ) -> None:
        """初始化记忆管理器 V2。

        Args:
            store: 长期记忆存储后端（MemoryStore 的子类）
            profile_store: 用户画像存储。为 None 时自动创建。
        """
        self.store = store
        self.profile_store = profile_store or ProfileStore()

        # Relationship Memory（延迟初始化，避免循环依赖）
        self._rel_memory_store = None
        self._consolidator = None

        # 子组件
        self._extractor = MemoryExtractor()
        self._retriever = MemoryRetriever(self.profile_store, self.store)

        logger.info("MemoryManager V2 初始化完成")

    @property
    def rel_memory_store(self):
        """延迟加载 RelationshipMemoryStore。"""
        if self._rel_memory_store is None:
            from memory.stores.relationship_memory_store import RelationshipMemoryStore
            self._rel_memory_store = RelationshipMemoryStore()
        return self._rel_memory_store

    @property
    def consolidator(self):
        """延迟加载 MemoryConsolidator。"""
        if self._consolidator is None:
            from memory.consolidator import MemoryConsolidator
            self._consolidator = MemoryConsolidator(self.rel_memory_store)
        return self._consolidator

    # ================================================================
    # V2 新接口：分类召回 + 分类提取
    # ================================================================

    async def get_context(
        self,
        platform: str,
        platform_user_id: str,
        query: str | None = None,
        memory_top_k: int = 5,
    ) -> "MemoryContext":
        """获取本次对话的完整记忆上下文（V2 入口）。

        Profile 常驻加载，LongMemory 按查询搜索。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            query: 用户当前消息（用于搜索 LongMemory）
            memory_top_k: LongMemory 召回数量

        Returns:
            MemoryContext（含 profile_context 和 memory_context）
        """
        result = await self._retriever.retrieve(
            platform, platform_user_id, query, memory_top_k,
        )
        return MemoryContext(
            profile_context=result.profile_context,
            memory_context=result.memory_context,
        )

    async def get_relationship_memory(
        self,
        platform: str,
        platform_user_id: str,
        limit: int = 3,
    ) -> str:
        """获取长期关系理解（V3 新增）。

        不与 Profile / LongMemory 混合。独立接口。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            limit: 返回数量上限

        Returns:
            格式化的关系理解 Prompt 文本
        """
        entries = await self.rel_memory_store.get_recent(
            platform, platform_user_id, limit,
        )
        return self.rel_memory_store.format_for_prompt(entries)

    async def consolidate_timeline(
        self,
        platform: str,
        platform_user_id: str,
        timeline_entries: list[dict],
        provider,
    ) -> int:
        """从 Timeline 中提炼关系理解（V3 新增）。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            timeline_entries: Timeline 条目列表
            provider: LLM Provider

        Returns:
            新增/更新的关系理解条数
        """
        return await self.consolidator.consolidate(
            platform, platform_user_id, timeline_entries, provider,
        )

    async def extract_and_store(
        self,
        platform: str,
        platform_user_id: str,
        user_message: str,
        ai_reply: str,
        provider,  # OpenAICompatibleProvider
    ) -> "ExtractResult":
        """从一轮对话中提取并存储记忆（V2 入口）。

        一次 LLM 调用，同时提取 Profile 更新和 LongMemory，
        分别存入 ProfileStore 和 MemoryStore。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            user_message: 用户消息
            ai_reply: AI 回复（原始版本）
            provider: LLM Provider

        Returns:
            ExtractResult（含 profile_count 和 memory_count）
        """
        # 1. LLM 提取
        extraction = await self._extractor.extract(
            user_message, ai_reply, provider,
        )

        profile_count = 0
        memory_count = 0

        # 2. 存储 Profile 更新
        if extraction.has_profile_updates:
            try:
                await self.profile_store.upsert(
                    platform, platform_user_id,
                    **extraction.profile_fields,
                )
                profile_count = len(extraction.profile_fields)
                logger.info(
                    f"Profile 已更新: [{platform}:{platform_user_id}] "
                    f"+{profile_count} 字段: {list(extraction.profile_fields.keys())}"
                )
            except Exception as e:
                logger.warning(f"Profile 存储失败: {e}")

        # 3. 存储 LongMemory（标记 source + evidence）
        if extraction.has_memories:
            for mem in extraction.memories:
                try:
                    await self.store.add(
                        platform=platform,
                        platform_user_id=platform_user_id,
                        key=mem["key"],
                        value=mem["value"],
                        importance=mem.get("importance", 5),
                        source="user_explicit",
                        evidence=user_message[:200],
                    )
                    memory_count += 1
                except Exception as e:
                    logger.warning(f"记忆存储失败: {e}")

        if profile_count > 0 or memory_count > 0:
            logger.info(
                f"记忆提取完成: [{platform}:{platform_user_id}] "
                f"Profile +{profile_count} | LongMemory +{memory_count}"
            )

        return ExtractResult(
            profile_count=profile_count,
            memory_count=memory_count,
        )

    # ================================================================
    # 兼容旧接口
    # ================================================================

    async def get_memory_context(
        self,
        platform: str,
        platform_user_id: str,
        query: str | None = None,
        top_k: int = 5,
    ) -> str:
        """获取格式化的记忆上下文（兼容旧接口）。

        内部使用 Retriever 的 LongMemory 格式化结果。
        推荐新代码使用 get_context() 获取完整上下文。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            query: 搜索查询
            top_k: 返回数量上限

        Returns:
            格式化的记忆文本。若无记忆则返回空字符串。
        """
        items = await self._retriever._search_or_list(
            platform, platform_user_id, query, top_k,
        )
        return self._retriever._format_memories(items)

    async def remember(
        self,
        platform: str,
        platform_user_id: str,
        key: str,
        value: str,
        importance: int = 5,
    ) -> None:
        """手动记住一条信息（LongMemory）。"""
        await self.store.add(platform, platform_user_id, key, value, importance)
        logger.debug(f"记忆已存储: [{platform}:{platform_user_id}] {key}={value[:30]}...")

    async def recall(
        self,
        platform: str,
        platform_user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryItem]:
        """回忆相关信息（LongMemory 搜索）。"""
        return await self.store.search(platform, platform_user_id, query, top_k)

    async def forget(self, platform: str, platform_user_id: str, key: str) -> bool:
        """忘记一条记忆（LongMemory）。"""
        return await self.store.delete(platform, platform_user_id, key)


# ================================================================
# 返回值类型
# ================================================================

class MemoryContext:
    """记忆召回结果。

    Attributes:
        profile_context: 用户画像 Prompt 文本
        memory_context: 长期记忆 Prompt 文本
    """

    def __init__(self, profile_context: str = "", memory_context: str = "") -> None:
        self.profile_context = profile_context
        self.memory_context = memory_context


class ExtractResult:
    """记忆提取结果。

    Attributes:
        profile_count: 更新的 Profile 字段数
        memory_count: 新增的 LongMemory 条数
    """

    def __init__(self, profile_count: int = 0, memory_count: int = 0) -> None:
        self.profile_count = profile_count
        self.memory_count = memory_count
