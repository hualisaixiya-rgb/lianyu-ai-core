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
from ai.world_tracker import (
    WorldState, ActiveTopics, ExpressionTracker,
    update_world_state, needs_llm_fallback, get_time_context,
    apply_rules,
)
from character.loader import CharacterLoader
from config.settings import get_settings
from database.repository import MessageRepository, UserRepository
from memory.manager import MemoryManager
from memory.stores.relationship_store import RelationshipStore
from memory.stores.sqlite_store import SQLiteMemoryStore
from prompt.manager import PromptManager


# 每个会话加载的历史消息数量上限
MAX_HISTORY_MESSAGES = 16

# ---- Intent Detection（纯规则，零 Token） ----

from enum import Enum, auto


class Intent(Enum):
    GREETING = auto()        # "你好""嗨""在吗"
    IDENTITY_CHECK = auto()  # "记得我吗""我是谁"
    RECALL_PAST = auto()     # "我们聊过什么""昨天"
    DEEP_TALK = auto()       # 长消息，深入话题
    DAILY_CHAT = auto()      # 普通日常聊天


# 身份确认关键词
IDENTITY_KEYWORDS = [
    "记得我吗", "还记得我吗", "我是谁", "我叫什么", "我的名字",
    "你是谁", "你还记得", "知不知道我",
]

# 回忆过去关键词（优先级高于身份确认）
RECALL_KEYWORDS = [
    "以前", "昨天", "前天", "上次", "聊过什么", "我们说过",
    "还记得那天", "之前", "之前不是",
]


def detect_intent(message: str) -> Intent:
    """纯规则检测用户意图。零 Token。"""
    msg = message.strip()

    # 1. 显式问候词
    if msg in ("你好呀", "你好", "嗨", "嗨嗨", "在吗", "在不在",
               "早", "早上好", "下午好", "晚上好", "晚安"):
        return Intent.GREETING

    # 2. 回忆过去（优先于身份确认 —— "还记得上次"是回忆不是确认身份）
    for kw in RECALL_KEYWORDS:
        if kw in msg:
            return Intent.RECALL_PAST

    # 3. 身份确认
    for kw in IDENTITY_KEYWORDS:
        if kw in msg:
            return Intent.IDENTITY_CHECK

    # 4. 短消息且不含实质内容 → 问候
    if len(msg) <= 3:
        return Intent.GREETING

    # 5. 深聊（长消息）
    if len(msg) > 25:
        return Intent.DEEP_TALK

    # 6. 默认日常
    return Intent.DAILY_CHAT


@dataclass
class ChatContext:
    """一次聊天的上下文信息。"""

    platform: str
    platform_user_id: str
    message: str
    username: str | None = None
    reply_to_message: str | None = None
    """用户正在回复的消息文本（Telegram reply / 引用回复）。

    当用户引用机器人之前的某条消息并追问时，
    此字段携带被引用消息的完整文本，
    帮助模型理解当前问题的上下文。
    """


@dataclass
class ChatResponse:
    """AI Core 的聊天响应。"""

    content: str
    tool_calls: list[dict] | None = None
    memory_updated: bool = False


@dataclass
class ConversationSession:
    """一个用户的对话会话（内存缓存）。

    Attributes:
        messages: 当前窗口内的对话历史（最近 N 条）
        loaded_from_db: 是否已从数据库加载
        summary: 滚动累积的对话摘要（结构化格式）
        pending_count: 自上次摘要后新增的消息数
        world_state: 当前世界状态（Rule Engine 维护，不写 DB）
        active_topics: 活跃话题管理器
        expression_tracker: 表达多样性追踪器
        _no_match_count: 连续未命中 Rule 的轮数
    """

    platform: str
    platform_user_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    loaded_from_db: bool = False
    summary: str = ""
    pending_count: int = 0
    world_state: WorldState | None = None
    active_topics: ActiveTopics | None = None
    expression_tracker: ExpressionTracker | None = None
    _no_match_count: int = 0


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
        self.relationship = RelationshipStore()

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
        2. 格式化用户消息（含引用回复上下文）
        3. 保存原始用户消息到数据库
        4. 加载对话历史 + 注入格式化消息
        5. 召回长期记忆
        6. 构建系统 Prompt（角色 + 世界 + 记忆 + 摘要）
        7. 调用 LLM 推理
        8. 清洗括号 → 保存 AI 回复
        9. 更新会话缓存
        10. 异步提取记忆 + 滚动摘要（不阻塞回复）

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

        # 1.5. Relationship：更新 Metrics（每次对话自动更新）
        try:
            await self.relationship.touch(
                context.platform, context.platform_user_id
            )
        except Exception:
            pass  # 非关键路径，静默失败

        # 1.6. Relationship：Touch Metrics + 加载 Timeline
        relationship_tone = ""
        timeline_context = ""
        try:
            await self.relationship.touch(
                context.platform, context.platform_user_id
            )
            timeline_context = await self.relationship.get_timeline_context(
                context.platform, context.platform_user_id
            )
        except Exception:
            pass  # 非关键路径

        # 2. 构造发送给 LLM 的用户消息（含引用上下文）
        user_message_for_llm = self._format_user_message(context)

        # 3. 保存用户消息到数据库（身份声明类标记为 context_visible=False）
        context_visible = not self._is_identity_declaration(context.message)
        await MessageRepository.save(
            platform=context.platform,
            platform_user_id=context.platform_user_id,
            role="user",
            content=context.message,
            context_visible=context_visible,
        )

        # 4. 加载对话历史（发送给 LLM 的消息使用含引用上下文的版本）
        session = self._get_session(context.platform, context.platform_user_id)
        if not session.loaded_from_db:
            db_history = await MessageRepository.get_recent_history(
                platform=context.platform,
                platform_user_id=context.platform_user_id,
                limit=MAX_HISTORY_MESSAGES,
            )
            session.messages = db_history
            session.loaded_from_db = True
        if context_visible:
            session.messages.append({"role": "user", "content": user_message_for_llm})

        # 5. Rule Engine：更新 World State + Active Topics（程序优先，零 Token）
        if session.world_state is None:
            session.world_state = WorldState()
        if session.active_topics is None:
            session.active_topics = ActiveTopics()
        if session.expression_tracker is None:
            session.expression_tracker = ExpressionTracker()

        # 5a. World State
        rule_hits = apply_rules(context.message)
        if rule_hits:
            session.world_state = update_world_state(
                context.message, session.world_state
            )
            session._no_match_count = 0
        else:
            session._no_match_count += 1

        # 5b. LLM Fallback（仅在 Rule 无法覆盖的复杂场景触发）
        if needs_llm_fallback(
            context.message, session.world_state, session._no_match_count
        ):
            try:
                fallback = await self._llm_world_state_fallback(
                    context.message, session.world_state
                )
                if fallback:
                    for f, v in fallback.items():
                        if v and hasattr(session.world_state, f):
                            setattr(session.world_state, f, v)
                    session._no_match_count = 0
            except Exception:
                pass  # Fallback 失败不影响主流程

        # 5c. Active Topics
        session.active_topics.update(context.message)

        # 6. 意图检测 + 选择性记忆召回
        intent = detect_intent(context.message)
        logger.debug(
            f"[{context.platform}:{context.platform_user_id}] "
            f"intent={intent.name}"
        )

        # Pending Resolution：有 pending + 消息像确认 → 消费 pending
        if await self._has_pending_identity(
            context.platform, context.platform_user_id
        ) and self._looks_like_confirmation(context.message):
            await self._resolve_pending_identity(
                context.platform, context.platform_user_id,
                context.message,
            )

        mem_ctx = await self.memory.get_context(
            platform=context.platform,
            platform_user_id=context.platform_user_id,
            query=context.message,
            memory_top_k=5,
        )

        # 根据意图选择性地使用记忆
        if intent == Intent.GREETING:
            # 问候：只用最小 Profile，不用 LongMemory/Summary/Timeline
            mem_ctx.memory_context = ""
            summary_for_prompt = ""
            timeline_for_prompt = ""
        elif intent == Intent.IDENTITY_CHECK:
            # 身份确认：用完整 Profile，硬注入确认名字，不用 LongMemory/Summary/Timeline
            mem_ctx.memory_context = ""
            summary_for_prompt = ""
            timeline_for_prompt = ""

            # 硬注入：从 Profile 中提取名字，直接告诉模型
            profile_name = await self._get_confirmed_name(
                context.platform, context.platform_user_id
            )
            if profile_name:
                mem_ctx.profile_context = (
                    f"【IDENTITY OVERRIDE】对方的名字（已确认）是：{profile_name}。"
                    "你的回复必须使用这个名字。不要使用聊天记录中看到的任何其他名字。"
                )
        elif intent == Intent.RECALL_PAST:
            # 回忆过去：用 Timeline + Profile，不用当前 Summary
            summary_for_prompt = ""
            timeline_for_prompt = await self.relationship.get_timeline_context(
                context.platform, context.platform_user_id
            )
        elif intent == Intent.DEEP_TALK:
            # 深聊：全量，含 Timeline
            summary_for_prompt = session.summary
            timeline_for_prompt = timeline_context
        else:  # DAILY_CHAT
            summary_for_prompt = session.summary
            timeline_for_prompt = timeline_context

        # 6.5. 关系理解（V3 新增）
        relationship_memory_context = ""
        try:
            relationship_memory_context = await self.memory.get_relationship_memory(
                context.platform, context.platform_user_id
            )
        except Exception:
            pass

        # 7. 构建系统 Prompt
        system_prompt = self._build_system_prompt(
            profile_context=mem_ctx.profile_context,
            memory_context=mem_ctx.memory_context,
            conversation_summary=summary_for_prompt,
            relationship_tone=relationship_tone,
            timeline_context=timeline_for_prompt,
            relationship_memory_context=relationship_memory_context,
            intent=intent,
            world_state=session.world_state,
            active_topics=session.active_topics,
        )

        # 8. 调用 LLM
        if get_settings().app.debug:
            self._dump_prompt(
                system_prompt=system_prompt,
                messages=session.messages,
                platform=context.platform,
                uid=context.platform_user_id,
                intent=intent,
            )

        try:
            # Chat History 包装：标记为"仅供上下文，不代表事实"
            wrapped_messages = [
                {"role": "system", "content": (
                    "以下聊天记录仅供上下文参考，不代表最终事实。"
                    "用户可能在对话中改过名字、纠正过信息、或随口说过不准确的话。"
                    "如果聊天记录中有人声称要改名（如'以后叫我X''我叫Y'），"
                    "但【已确认】中仍是旧名字——以旧名字为准。未确认的改名不是事实。"
                    "以 System Prompt 中的【已确认】信息为最高优先级。"
                )}
            ] + list(session.messages)

            reply = await self.provider.chat(
                messages=wrapped_messages,
                system_prompt=system_prompt,
            )
        except ValueError as e:
            logger.error(f"配置错误: {e}")
            return ChatResponse(content=f"配置错误：{e}")
        except RuntimeError as e:
            logger.error(f"LLM 调用失败: {e}")
            return ChatResponse(content="……")

        # 9. 清洗括号 → 保存纯净版本，打破括号自循环
        from utils.response_renderer import render_for_storage
        clean_reply = render_for_storage(reply)

        await MessageRepository.save(
            platform=context.platform,
            platform_user_id=context.platform_user_id,
            role="assistant",
            content=clean_reply,
            context_visible=context_visible,
        )

        # 10. 更新会话缓存（身份声明消息跳过，不污染上下文）
        if context_visible:
            session.messages.append({"role": "assistant", "content": clean_reply})

        # 10.5. 追踪待摘要消息数，超过阈值触发滚动摘要
        session.pending_count += 2
        if session.pending_count >= 12 and len(session.messages) >= 8:
            asyncio.create_task(
                self._summarize_async(context, session)
            )

        # 10.6. Timeline 生成：Summary 更新后异步生成今日 Timeline
        if session.summary and len(session.summary) > 20:
            asyncio.create_task(
                self._generate_timeline_async(context, session.summary)
            )

        # 11. 异步提取 Profile（不阻塞本次回复）
        asyncio.create_task(
            self._extract_profile_async(context, reply)
        )

        logger.info(
            f"[{context.platform}] 回复: "
            f"{context.username or context.platform_user_id} <- {reply[:50]}"
        )

        memory_updated = bool(mem_ctx.profile_context or mem_ctx.memory_context)
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

    def _format_user_message(self, context: ChatContext) -> str:
        """格式化发送给 LLM 的用户消息。

        当用户引用回复了机器人的某条消息时，
        将被引用内容作为前缀注入，
        帮助模型理解"用户正在回复哪句话"。

        Args:
            context: 聊天上下文

        Returns:
            格式化后的用户消息（可能含引用前缀）
        """
        if not context.reply_to_message:
            return context.message

        # 格式：[用户正在回复你之前说的这段话]\n「被引用内容」\n[用户接着问]\n<当前消息>
        quoted = context.reply_to_message.strip()
        return (
            f"[用户正在回复你之前说的这段话]\n"
            f"绘梨衣：「{quoted}」\n"
            f"[用户接着问]\n"
            f"{context.message}"
        )

    async def _llm_world_state_fallback(
        self, user_message: str, current: WorldState
    ) -> dict[str, str] | None:
        """LLM Fallback：仅用于复杂语义的 World State 提取。

        只在 Rule Engine 无法解析时调用（~5% 场景）。
        使用极简 Prompt，目标 ~50 tokens input + ~50 tokens output。

        Args:
            user_message: 用户消息
            current: 当前 World State

        Returns:
            更新字段 dict，失败返回 None
        """
        import json

        current_json = {
            "location": current.location or None,
            "activity": current.activity or None,
            "temperature_feeling": current.temperature_feeling or None,
            "sky": current.sky or None,
            "wind": current.wind or None,
            "user_mood": current.user_mood or None,
            "crowd": current.crowd or None,
        }

        prompt = (
            "从这句话提取状态，只返回JSON，不解释：\n"
            f"\"{user_message}\"\n\n"
            f"当前状态：{json.dumps(current_json, ensure_ascii=False)}\n"
            "规则：只提取明确说出的。不推断。\n"
            '{"location":"...","activity":"...","temperature_feeling":"...",'
            '"sky":"...","wind":"...","user_mood":"...","crowd":"..."}'
        )

        try:
            raw = await self.provider.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="你是一个状态提取器。只返回JSON。不解释。不推断。",
            )
            # 提取 JSON
            text = raw.strip()
            if "```" in text:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    text = text[start:end]
            result = json.loads(text)
            if isinstance(result, dict):
                return {
                    k: v for k, v in result.items()
                    if v and isinstance(v, str) and hasattr(current, k)
                }
        except Exception:
            pass
        return None

    @staticmethod
    def _dump_prompt(
        system_prompt: str,
        messages: list[dict[str, str]],
        platform: str = "",
        uid: str = "",
        intent: Intent | None = None,
    ) -> None:
        """Debug: 打印最终发送给 LLM 的完整 Prompt。"""
        sep = "=" * 60
        logger.info(f"{sep} PROMPT DUMP [{platform}:{uid}] intent={intent.name if intent else '?'} {sep}")

        # 分割 System Prompt 各部分（按模板占位符标记）
        logger.info("--- SYSTEM PROMPT (full, {} chars) ---", len(system_prompt))
        for i, line in enumerate(system_prompt.split("\n"), 1):
            logger.info("S{:04d}| {}", i, line)

        logger.info("--- HISTORY ({} messages) ---", len(messages))
        for i, msg in enumerate(messages, 1):
            role = msg.get("role", "?")
            content = msg.get("content", "")
            # 截断过长消息
            if len(content) > 200:
                content = content[:200] + f"...({len(content)} chars)"
            logger.info("H{:04d}| [{}] {}", i, role, content)

        logger.info(f"{sep} END PROMPT DUMP {sep}")

    def _get_session(self, platform: str, platform_user_id: str) -> ConversationSession:
        """获取或创建用户会话（内存缓存）。"""
        session_key = f"{platform}:{platform_user_id}"
        if session_key not in self._sessions:
            self._sessions[session_key] = ConversationSession(
                platform=platform,
                platform_user_id=platform_user_id,
            )
        return self._sessions[session_key]

    def _build_system_prompt(
        self,
        profile_context: str = "",
        memory_context: str = "",
        conversation_summary: str = "",
        relationship_tone: str = "",
        timeline_context: str = "",
        relationship_memory_context: str = "",
        intent: Intent | None = None,
        world_state: WorldState | None = None,
        active_topics: ActiveTopics | None = None,
    ) -> str:
        """构建完整的 System Prompt（V3 选择性注入）。

        Args:
            profile_context: 用户画像上下文
            memory_context: 长期记忆上下文
            conversation_summary: 滚动摘要
            relationship_tone: 语气指导
            timeline_context: Timeline（最近关系事件）
            relationship_memory_context: 长期关系理解（V3 新增）
            intent: 用户意图
            world_state: 当前世界状态
            active_topics: 活跃话题

        Returns:
            完整的 System Prompt 字符串
        """
        from utils.world_state import get_world_context

        identity = self._character.to_identity()
        world_context = get_world_context()
        time_context = get_time_context()

        # 摘要（仅非问候/身份确认时注入）
        summary_block = ""
        if conversation_summary:
            summary_block = f"你们之前聊过：\n{conversation_summary}"

        # Timeline（仅回忆过去时注入）
        timeline_block = ""
        if timeline_context:
            timeline_block = f"【你们一起经历过……】\n{timeline_context}"

        # World State
        world_state_block = ""
        if world_state and not world_state.is_empty():
            world_state_block = world_state.to_prompt()

        # Active Topics
        topics_block = ""
        if active_topics and not active_topics.is_empty():
            topics_block = active_topics.to_prompt()

        return self.prompt_manager.render(
            "system",
            identity=identity,
            current_time=time_context,
            world_context=world_context,
            profile_context=profile_context,
            memory_context=memory_context,
            conversation_summary=summary_block,
            relationship_tone=relationship_tone,
            timeline_context=timeline_block,
            relationship_memory_context=relationship_memory_context,
            world_state_context=world_state_block,
            active_topics_context=topics_block,
        )

    async def _summarize_async(
        self, context: ChatContext, session: ConversationSession
    ) -> None:
        """异步滚动摘要：将窗口外的旧消息压缩为结构化摘要。

        取 session.messages 最旧的 8 条，调用 LLM 生成/合并摘要，
        然后从 session.messages 中移除已摘要的消息。
        """
        try:
            from memory.summarizer import ConversationSummarizer

            summarizer = ConversationSummarizer()
            batch = session.messages[:8]
            new_summary = await summarizer.summarize(
                messages=batch,
                existing_summary=session.summary,
                provider=self.provider,
            )
            session.summary = new_summary
            session.messages = session.messages[8:]
            session.pending_count = 0
            logger.info(
                f"对话摘要更新: [{context.platform}:{context.platform_user_id}] "
                f"摘要={len(new_summary)}字 | 剩余消息={len(session.messages)}条"
            )
        except Exception as e:
            logger.warning(f"后台摘要失败: {e}")

    async def _generate_timeline_async(
        self, context: ChatContext, summary: str
    ) -> None:
        """从对话摘要生成今日 Timeline + 触发关系理解提炼（后台运行）。"""
        try:
            result = await self.relationship.generate_timeline_if_needed(
                context.platform,
                context.platform_user_id,
                summary,
                self.provider,
            )
            # 如果生成了 Timeline，触发关系理解提炼
            if result:
                asyncio.create_task(
                    self.memory.consolidate_timeline(
                        context.platform,
                        context.platform_user_id,
                        [result],
                        self.provider,
                    )
                )
        except Exception as e:
            logger.warning(f"Timeline 生成失败: {e}")

    async def _extract_profile_async(
        self, context: ChatContext, ai_reply: str
    ) -> None:
        """异步提取 Profile（后台运行，不影响回复速度）。

        identity intent → 不调 LLM，直接创建 pending。
        NAME_CHANGE_CONFIRM → 调 LLM 提取，正常 applied。
        """
        from memory.extractor import MemoryExtractor
        intent = MemoryExtractor._detect_profile_intent(context.message)

        # 身份声明 intent → 绕过 LLM，直接创建 pending
        if intent in ("NAME_INTRO", "NICKNAME_SET", "NAME_CHANGE_REQUEST"):
            await self._create_pending_identity(
                context, intent,
            )
            return

        # 其他非身份场景 → 走正常的 _should_extract 守卫
        if not self._should_extract(context.message, ai_reply):
            return

        try:
            result = await self.memory.extract_and_store(
                platform=context.platform,
                platform_user_id=context.platform_user_id,
                user_message=context.message,
                ai_reply=ai_reply,
                provider=self.provider,
            )
            if result.profile_count > 0:
                logger.info(
                    f"Profile 已更新: [{context.platform}:{context.platform_user_id}] "
                    f"+{result.profile_count} 字段"
                )
        except Exception as e:
            logger.warning(f"Profile 提取失败: {e}")

    async def _has_pending_identity(
        self, platform: str, platform_user_id: str
    ) -> bool:
        """检查是否有待确认的身份记录。"""
        from database.models.profile import ProfileHistory
        from database.session import AsyncSessionLocal
        from sqlalchemy import select, func as sql_func

        try:
            async with AsyncSessionLocal.get_session() as session:
                stmt = select(sql_func.count()).select_from(ProfileHistory).where(
                    ProfileHistory.platform == platform,
                    ProfileHistory.platform_user_id == platform_user_id,
                    ProfileHistory.status == "pending",
                )
                result = await session.execute(stmt)
                return result.scalar_one() > 0
        except Exception:
            return False

    @staticmethod
    def _looks_like_confirmation(message: str) -> bool:
        """检测消息是否为确认语句。"""
        msg = message.strip()

        # 短消息 + 确认关键词
        if len(msg) > 15:
            return False

        confirm_words = [
            "对", "就这个", "就叫", "就它", "就按",
            "嗯", "可以", "行", "好", "是的", "没错",
            "确定了", "就这样", "不改了",
        ]
        return any(kw in msg for kw in confirm_words)

    async def _resolve_pending_identity(
        self, platform: str, platform_user_id: str, confirm_msg: str
    ) -> None:
        """消费最近的 pending 身份记录 → confirmed → 写入 user_profiles。

        在 chat() 主流程中、build_prompt() 之前调用。
        同一轮内 LLM 就能看到更新后的 Profile。
        """
        from database.models.profile import ProfileHistory
        from database.session import AsyncSessionLocal
        from sqlalchemy import desc, select, update as sql_update

        try:
            async with AsyncSessionLocal.get_session() as session:
                # 读取最近的 pending 记录
                stmt = (
                    select(ProfileHistory)
                    .where(
                        ProfileHistory.platform == platform,
                        ProfileHistory.platform_user_id == platform_user_id,
                        ProfileHistory.status == "pending",
                    )
                    .order_by(desc(ProfileHistory.created_at))
                    .limit(1)
                )
                result = await session.execute(stmt)
                pending = result.scalar_one_or_none()

                if pending is None:
                    return

                # 更新 profile_history → confirmed
                pid = pending.id
                from sqlalchemy import text
                await session.execute(
                    text("UPDATE profile_history SET status='confirmed', evidence=:ev WHERE id=:id"),
                    {"ev": f"{pending.evidence or ''}; confirmed: {confirm_msg[:100]}", "id": pid},
                )

                # 写入 user_profiles
                from database.models.profile import UserProfile
                from sqlalchemy import select as sel
                stmt2 = sel(UserProfile).where(
                    UserProfile.platform == platform,
                    UserProfile.platform_user_id == platform_user_id,
                )
                r2 = await session.execute(stmt2)
                row = r2.scalar_one_or_none()
                if row is None:
                    row = UserProfile(
                        platform=platform, platform_user_id=platform_user_id,
                        **{pending.field_name: pending.new_value},
                    )
                    session.add(row)
                else:
                    setattr(row, pending.field_name, pending.new_value)

                await session.flush()
                logger.info(
                    f"Pending resolved: [{platform}:{platform_user_id}] "
                    f"{pending.field_name}={pending.new_value!r} → confirmed"
                )
        except Exception as e:
            logger.warning(f"Pending resolution 失败: {e}")

    async def _create_pending_identity(
        self, context: ChatContext, intent: str
    ) -> None:
        """绕过 LLM + upsert，直接在 profile_history 创建 pending。

        不修改 user_profiles。
        """
        import re
        from database.models.profile import ProfileHistory
        from database.session import AsyncSessionLocal

        msg = context.message.strip()
        value = None
        field_name = "name"

        if intent == "NAME_INTRO":
            field_name = "name"
            for pat in [r"我叫(.+)", r"我的名字[是叫](.+)", r"我是(.+)"]:
                m = re.match(pat, msg)
                if m:
                    value = m.group(1).strip().rstrip("，,。！!")
                    break
        elif intent == "NICKNAME_SET":
            field_name = "nickname"
            for pat in [r"(?:以后|以后你|你以后|你可以|可以|平时)?(?:喊|叫)我(.+)"]:
                m = re.search(pat, msg)
                if m:
                    raw = m.group(1).strip()
                    # 去掉尾部语气词
                    value = re.sub(r"[吧呀啊哦嘛呢]$", "", raw).strip()
                    break
        elif intent == "NAME_CHANGE_REQUEST":
            field_name = "name"
            for pat in [r"把名字改成(.+)", r"名字改成(.+)", r"改[个成]名字[为叫]?(.+)",
                       r"改名[为叫]?(.+)"]:
                m = re.match(pat, msg)
                if m:
                    value = m.group(1).strip().rstrip("，,。！!吧")
                    break

        if not value or len(value) > 20:
            return

        # 读旧值
        old_value = None
        try:
            profile = await self.memory.profile_store.get(
                context.platform, context.platform_user_id
            )
            if profile:
                old_value = profile.get_field(field_name)
        except Exception:
            pass

        from memory.extractor import MemoryExtractor
        confidence = MemoryExtractor._compute_confidence(context.message, field_name)

        # 直接写 profile_history，不修改 user_profiles
        try:
            async with AsyncSessionLocal.get_session() as session:
                entry = ProfileHistory(
                    platform=context.platform,
                    platform_user_id=context.platform_user_id,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=value,
                    confidence=confidence,
                    evidence=context.message[:500],
                    status="pending",
                )
                session.add(entry)
            logger.info(
                f"Profile pending: [{context.platform}:{context.platform_user_id}] "
                f"intent={intent} {field_name}={value!r} conf={confidence}"
            )
        except Exception as e:
            logger.warning(f"Profile pending 创建失败: {e}")

    async def _get_confirmed_name(
        self, platform: str, platform_user_id: str
    ) -> str | None:
        """获取已确认的用户姓名（仅 applied，不含 pending）。"""
        try:
            profile = await self.memory.profile_store.get(
                platform, platform_user_id
            )
            if profile and profile.name:
                return profile.name
        except Exception:
            pass
        return None

    @staticmethod
    def _is_identity_declaration(message: str) -> bool:
        """检测是否为身份声明消息。

        任何身份 intent → context_visible=False。
        不注入 LLM 上下文，数据库保留完整记录。
        """
        from memory.extractor import MemoryExtractor

        msg = message.strip()
        intent = MemoryExtractor._detect_profile_intent(msg)
        return intent in (
            "NAME_INTRO", "NICKNAME_SET", "NAME_CHANGE_REQUEST",
            "NAME_CHANGE_CONFIRM",
        )

    @staticmethod
    def _should_extract(user_message: str, ai_reply: str) -> bool:
        """Profile 提取守卫。

        NAME_INTRO / NICKNAME_SET / NAME_CHANGE_REQUEST → 阻断（进入 pending）。
        NAME_CHANGE_CONFIRM → 允许（显式确认）。
        """
        from memory.extractor import MemoryExtractor

        intent = MemoryExtractor._detect_profile_intent(user_message)

        # 以下 intent → 阻断，不直接 applied
        if intent in ("NAME_INTRO", "NICKNAME_SET", "NAME_CHANGE_REQUEST"):
            return False

        # 显式确认 → 允许
        if intent == "NAME_CHANGE_CONFIRM":
            return True

        return MemoryExtractor._can_extract_profile(user_message)
