"""AI Core 核心类。

这是整个项目的推理中枢。所有 Adapter（Telegram/微信/Web）
都通过这个类的接口调用 AI，不直接与 LLM 交互。

设计原则：
- 单一入口：所有消息处理走 AICore.chat()
- 组合各个模块：Memory、Character、Prompt、Tools
- 不依赖任何具体 Adapter
"""

import asyncio
from datetime import datetime
from dataclasses import dataclass, field

from loguru import logger

from ai.providers.openai_compatible import OpenAICompatibleProvider
from character.loader import CharacterLoader
from config.settings import get_settings
from database.repository import MessageRepository, UserRepository
from memory.manager import MemoryManager
from memory.stores.sqlite_store import SQLiteMemoryStore
from prompt.manager import PromptManager


# 每个会话加载的历史消息数量上限
MAX_HISTORY_MESSAGES = 16


@dataclass
class ChatContext:
    """一次聊天的上下文信息。"""

    platform: str
    platform_user_id: str
    message: str
    username: str | None = None


@dataclass
class ChatResponse:
    """AI Core 的聊天响应。"""

    content: str
    tool_calls: list[dict] | None = None
    memory_updated: bool = False


@dataclass
class ConversationSession:
    """一个用户的对话会话（内存缓存）。"""

    platform: str
    platform_user_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    loaded_from_db: bool = False


class AICore:
    """AI 推理核心。

    组合 Memory、Character、Prompt、Tools 模块，
    完成一次完整的 AI 对话推理。

    使用方式：
        core = AICore()
        response = await core.chat(context)
    """

    def __init__(
        self,
        provider: OpenAICompatibleProvider | None = None,
        character_loader: CharacterLoader | None = None,
        prompt_manager: PromptManager | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        """初始化 AI Core。

        Args:
            provider: LLM 提供商实例。
            character_loader: 角色加载器。
            prompt_manager: Prompt 管理器。
            memory_manager: 记忆管理器。
        """
        self.provider = provider or OpenAICompatibleProvider()
        self.character_loader = character_loader or CharacterLoader()
        self.prompt_manager = prompt_manager or PromptManager()
        self.memory = memory_manager or MemoryManager(SQLiteMemoryStore())

        # 当前角色
        self._character_name = get_settings().character.name
        self._character = self.character_loader.load(self._character_name)

        # 会话缓存
        self._sessions: dict[str, ConversationSession] = {}

        logger.info(
            f"AI Core 初始化完成 | 角色={self._character.display_name} | "
            f"模型={self.provider.model} | 记忆=SQLite"
        )

    # ================================================================
    # 公开接口
    # ================================================================

    async def chat(self, context: ChatContext) -> ChatResponse:
        """处理一次聊天请求。

        完整流程：
        1. 注册用户
        2. 保存用户消息到数据库
        3. 加载对话历史
        4. 召回长期记忆 → 注入 System Prompt
        5. 构建系统 Prompt（角色 + 系统规则 + 记忆）
        6. 调用 LLM 推理
        7. 保存 AI 回复到数据库
        8. 更新会话缓存
        9. 异步提取新记忆（不阻塞回复）

        Args:
            context: 聊天上下文

        Returns:
            ChatResponse: AI 的回复内容
        """
        logger.info(
            f"[{context.platform}] {context.username or context.platform_user_id}: "
            f"{context.message[:50]}"
        )

        # 1. 注册用户
        await UserRepository.get_or_create(
            platform=context.platform,
            platform_user_id=context.platform_user_id,
            username=context.username,
        )

        # 2. 保存用户消息
        await MessageRepository.save(
            platform=context.platform,
            platform_user_id=context.platform_user_id,
            role="user",
            content=context.message,
        )

        # 3. 加载对话历史
        session = self._get_session(context.platform, context.platform_user_id)
        if not session.loaded_from_db:
            db_history = await MessageRepository.get_recent_history(
                platform=context.platform,
                platform_user_id=context.platform_user_id,
                limit=MAX_HISTORY_MESSAGES,
            )
            session.messages = db_history
            session.loaded_from_db = True
        else:
            session.messages.append({"role": "user", "content": context.message})

        # 4. 召回长期记忆
        memory_context = await self.memory.get_memory_context(
            platform=context.platform,
            platform_user_id=context.platform_user_id,
            query=context.message,
            top_k=5,
        )

        # 5. 构建系统 Prompt（含记忆）
        system_prompt = self._build_system_prompt(memory_context)

        # 6. 调用 LLM
        try:
            reply = await self.provider.chat(
                messages=session.messages,
                system_prompt=system_prompt,
            )
        except ValueError as e:
            logger.error(f"配置错误: {e}")
            return ChatResponse(content=f"配置错误：{e}")
        except RuntimeError as e:
            logger.error(f"LLM 调用失败: {e}")
            return ChatResponse(content="……")

        # 7. 清洗括号 → 保存纯净版本，打破括号自循环
        from utils.response_renderer import render_for_storage
        clean_reply = render_for_storage(reply)

        await MessageRepository.save(
            platform=context.platform,
            platform_user_id=context.platform_user_id,
            role="assistant",
            content=clean_reply,
        )

        # 8. 更新会话缓存（用纯净版本）
        session.messages.append({"role": "assistant", "content": clean_reply})

        # 9. 异步提取记忆（不阻塞本次回复）
        asyncio.create_task(
            self._extract_memories_async(context, reply)
        )

        logger.info(
            f"[{context.platform}] 回复: "
            f"{context.username or context.platform_user_id} <- {reply[:50]}"
        )

        memory_updated = bool(memory_context)
        return ChatResponse(content=reply, memory_updated=memory_updated)

    async def clear_session(self, platform: str, platform_user_id: str) -> None:
        """清除指定用户的对话历史缓存。"""
        session_key = f"{platform}:{platform_user_id}"
        self._sessions.pop(session_key, None)
        logger.info(f"会话缓存已清除: {session_key}")

    def get_history(self, platform: str, platform_user_id: str) -> list[dict[str, str]]:
        """获取对话历史（只读，从内存缓存）。"""
        session = self._get_session(platform, platform_user_id)
        return list(session.messages)

    async def reload_history(self, platform: str, platform_user_id: str) -> list[dict[str, str]]:
        """从数据库重新加载对话历史。"""
        session_key = f"{platform}:{platform_user_id}"
        self._sessions.pop(session_key, None)
        db_history = await MessageRepository.get_recent_history(
            platform=platform,
            platform_user_id=platform_user_id,
            limit=MAX_HISTORY_MESSAGES,
        )
        self._sessions[session_key] = ConversationSession(
            platform=platform,
            platform_user_id=platform_user_id,
            messages=db_history,
            loaded_from_db=True,
        )
        return db_history

    # ================================================================
    # 内部方法
    # ================================================================

    def _get_session(self, platform: str, platform_user_id: str) -> ConversationSession:
        """获取或创建用户会话（内存缓存）。"""
        session_key = f"{platform}:{platform_user_id}"
        if session_key not in self._sessions:
            self._sessions[session_key] = ConversationSession(
                platform=platform,
                platform_user_id=platform_user_id,
            )
        return self._sessions[session_key]

    def _build_system_prompt(self, memory_context: str = "") -> str:
        """构建完整的 System Prompt。

        结构顺序：[1]身份锁 [2]行为 [3]输出 [4]情绪 [5]角色 [6]记忆

        Args:
            memory_context: 记忆上下文（来自 MemoryManager）

        Returns:
            完整的 System Prompt 字符串
        """
        identity = self._character.to_identity()
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        return self.prompt_manager.render(
            "system",
            identity=identity,
            current_time=now,
            memory_context=memory_context,
        )

    async def _extract_memories_async(
        self, context: ChatContext, ai_reply: str
    ) -> None:
        """异步提取本轮对话中的记忆（后台运行，不影响回复速度）。

        Args:
            context: 聊天上下文
            ai_reply: AI 的回复内容
        """
        try:
            count = await self.memory.extract_and_store(
                platform=context.platform,
                platform_user_id=context.platform_user_id,
                user_message=context.message,
                ai_reply=ai_reply,
                provider=self.provider,
            )
            if count > 0:
                logger.info(
                    f"记忆已更新: [{context.platform}:{context.platform_user_id}] "
                    f"+{count} 条"
                )
        except Exception as e:
            logger.warning(f"后台记忆提取失败: {e}")
