"""记忆管理器。

负责记忆的增删查、LLM 提取、格式化输出。
"""

import json

from loguru import logger

from memory.base import MemoryItem, MemoryStore


class MemoryManager:
    """记忆管理器。

    封装 MemoryStore + LLM 提取，提供业务级别的记忆操作。

    使用方式：
        store = SQLiteMemoryStore()
        manager = MemoryManager(store)
        await manager.remember(platform, uid, "我叫小明", "用户叫小明", 8)
        context = await manager.get_memory_context(platform, uid, query="名字")
        await manager.extract_and_store(platform, uid, user_msg, ai_reply, provider)
    """

    def __init__(self, store: MemoryStore) -> None:
        """初始化记忆管理器。

        Args:
            store: 记忆存储后端实例（MemoryStore 的子类）
        """
        self.store = store
        # 延迟加载 PromptManager
        self._extraction_prompt: str | None = None
        logger.info("MemoryManager 初始化完成")

    async def remember(
        self,
        platform: str,
        platform_user_id: str,
        key: str,
        value: str,
        importance: int = 5,
    ) -> None:
        """手动记住一条信息。"""
        await self.store.add(platform, platform_user_id, key, value, importance)
        logger.debug(f"记忆已存储: [{platform}:{platform_user_id}] {key}={value[:30]}...")

    async def recall(
        self,
        platform: str,
        platform_user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryItem]:
        """回忆相关信息。"""
        return await self.store.search(platform, platform_user_id, query, top_k)

    async def get_memory_context(
        self,
        platform: str,
        platform_user_id: str,
        query: str | None = None,
        top_k: int = 5,
    ) -> str:
        """获取格式化的记忆上下文，可直接拼入 Prompt。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            query: 搜索查询（为 None 时返回最近记忆）
            top_k: 返回数量上限

        Returns:
            格式化的记忆文本。若无记忆则返回空字符串。
        """
        if query:
            items = await self.store.search(platform, platform_user_id, query, top_k)
        else:
            items = await self.store.list_all(platform, platform_user_id)

        if not items:
            return ""

        # 按重要性降序
        items.sort(key=lambda x: x.importance, reverse=True)
        items = items[:top_k]

        lines = ["你对这个聊天对象的记忆："]
        for item in items:
            lines.append(f"- {item.value}")

        return "\n".join(lines)

    async def extract_and_store(
        self,
        platform: str,
        platform_user_id: str,
        user_message: str,
        ai_reply: str,
        provider,  # OpenAICompatibleProvider
    ) -> int:
        """从一轮对话中提取记忆并存储。

        使用 LLM 分析本轮对话，自动提取用户的关键信息
        （姓名、偏好、重要事件等），然后存入记忆库。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            user_message: 用户消息
            ai_reply: AI 回复
            provider: LLM Provider（用于调用提取 Prompt）

        Returns:
            本次提取的记忆条数（0 表示没有值得记住的信息）
        """
        # 构建提取 Prompt
        extraction_prompt = self._get_extraction_prompt()
        conversation = f"用户: {user_message}\nAI: {ai_reply}"

        try:
            result = await provider.chat(
                messages=[{"role": "user", "content": conversation}],
                system_prompt=extraction_prompt,
            )
        except Exception as e:
            logger.warning(f"记忆提取失败（LLM 调用异常）: {e}")
            return 0

        # 解析 JSON 结果
        memories = self._parse_extraction_result(result)
        if not memories:
            return 0

        # 存入记忆库
        stored = 0
        for mem in memories:
            try:
                await self.store.add(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    key=mem["key"],
                    value=mem["value"],
                    importance=min(max(mem.get("importance", 5), 1), 10),
                )
                stored += 1
            except Exception as e:
                logger.warning(f"存储记忆失败: {e}")

        if stored > 0:
            logger.info(
                f"记忆提取完成: [{platform}:{platform_user_id}] 新增 {stored} 条记忆"
            )

        return stored

    async def forget(self, platform: str, platform_user_id: str, key: str) -> bool:
        """忘记一条记忆。"""
        return await self.store.delete(platform, platform_user_id, key)

    # ================================================================
    # 内部方法
    # ================================================================

    def _get_extraction_prompt(self) -> str:
        """获取记忆提取的 System Prompt（从模板加载）。"""
        if self._extraction_prompt is None:
            from prompt.manager import PromptManager
            pm = PromptManager()
            self._extraction_prompt = pm.get("memory_extraction") or ""
        return self._extraction_prompt

    @staticmethod
    def _parse_extraction_result(text: str) -> list[dict]:
        """解析 LLM 返回的记忆提取结果。

        兼容多种格式：纯 JSON 数组、带 markdown 代码块的 JSON。

        Args:
            text: LLM 返回的原始文本

        Returns:
            解析后的记忆列表，格式 [{"key": "...", "value": "...", "importance": 5}, ...]
        """
        # 尝试提取 JSON 代码块
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end]
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end]

        text = text.strip()

        try:
            result = json.loads(text)
            if isinstance(result, list):
                # 验证每条记忆格式
                valid = []
                for item in result:
                    if isinstance(item, dict) and "key" in item and "value" in item:
                        valid.append(item)
                return valid
        except json.JSONDecodeError:
            logger.debug(f"记忆提取结果无法解析为 JSON: {text[:100]}...")

        return []
