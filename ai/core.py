"""AI Core 核心类。

这是整个项目的推理中枢。所有 Adapter（Telegram/微信/Web）
都通过这个类的接口调用 AI，不直接与 LLM 交互。

设计原则：
- 单一入口：所有消息处理走 AICore.chat()
- 组合各个模块：Memory、Character、Prompt、Tools
- 不依赖任何具体 Adapter
"""

import asyncio
from dataclasses import dataclass, field

from loguru import logger

from ai.identity import IdentityFlow
from ai.intent import Intent, detect_intent
from ai.message_formatter import format_user_message
from ai.prompt_builder import PromptBuilder, PromptContext
from ai.providers.openai_compatible import OpenAICompatibleProvider
from ai.session_manager import ConversationSession, SessionManager, MAX_HISTORY_MESSAGES
from ai.world_tracker import WorldState, ActiveTopics
from ai.world_updater import WorldStateUpdater
from character.loader import CharacterLoader
from config.settings import get_settings
from database.repository import MessageRepository, UserRepository
from memory.manager import MemoryManager
from memory.stores.relationship_store import RelationshipStore
from memory.stores.sqlite_store import SQLiteMemoryStore
from prompt.manager import PromptManager


# 后台异步任务的默认超时时间（秒）
BACKGROUND_TASK_TIMEOUT = 30.0


def _create_background_task(coro, timeout: float = BACKGROUND_TASK_TIMEOUT):
    """创建带 timeout 的后台异步任务。

    超时后任务被静默取消，记录 warning 日志。
    """
    async def _wrapped():
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"后台任务超时 ({timeout}s): {coro.__qualname__}")
        except Exception as e:
            logger.warning(f"后台任务异常: {coro.__qualname__}: {e}")

    return asyncio.create_task(_wrapped())


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

        # PromptBuilder（依赖注入，渲染 System Prompt）
        self.prompt_builder = PromptBuilder(
            prompt_manager=self.prompt_manager,
            character=self._character,
        )

        # SessionManager（会话缓存，Phase B1 迁移）
        self.sessions = SessionManager()
        # 兼容别名：_sessions 指向同一缓存 dict（外部代码/脚本直接访问 _sessions）
        self._sessions = self.sessions._sessions

        # IdentityFlow（Orchestrator 子组件，Phase B2 迁移）
        # 注入 profile_store（只读协调，不修改其逻辑）
        self.identity_flow = IdentityFlow(profile_store=self.memory.profile_store)

        # WorldStateUpdater（Step 5a/5b/5c 编排，Phase B3 迁移）
        self.world_updater = WorldStateUpdater(provider=self.provider)

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

        # 1.5. Relationship：Touch Metrics + 加载 Timeline
        relationship_tone = ""
        timeline_context = ""
        try:
            await self.relationship.touch(
                context.platform, context.platform_user_id
            )
            timeline_context = await self.relationship.get_timeline_context(
                context.platform, context.platform_user_id
            )
        except Exception as e:
            logger.debug(f"Relationship touch/timeline 失败: {e}")

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

        # 5. Rule Engine：更新 World State + Active Topics（Phase B3 委托 world_updater）
        self.world_updater.ensure_initialized(session)

        # 5a. World State（程序优先，零 Token）
        self.world_updater.apply_rules(session, context.message)

        # 5b. LLM Fallback（仅在 Rule 无法覆盖的复杂场景触发）
        await self.world_updater.llm_fallback(session, context.message)

        # 5c. Active Topics
        self.world_updater.update_topics(session, context.message)

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

            # V3.5: 三级回退 confirmed → candidate → none
            profile_name, name_level = await self._get_confirmed_name(
                context.platform, context.platform_user_id
            )
            if profile_name:
                if name_level == "confirmed":
                    mem_ctx.profile_context = (
                        f"【IDENTITY OVERRIDE】对方的名字（已确认）是：{profile_name}。"
                        "你的回复必须使用这个名字。不要使用聊天记录中看到的任何其他名字。"
                    )
                else:  # candidate
                    mem_ctx.profile_context = (
                        f"【IDENTITY OVERRIDE】对方曾自称：{profile_name}。"
                        "这尚未确认。如果对方最新的说法不同，以最新为准。"
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

        # 6.5. 关系理解 + 情绪趋势（V3.5.1: 仅 DEEP_TALK / RECALL_PAST 注入）
        relationship_memory_context = ""
        emotion_trend = ""
        if intent in (Intent.DEEP_TALK, Intent.RECALL_PAST):
            try:
                relationship_memory_context = await self.memory.get_relationship_memory(
                    context.platform, context.platform_user_id
                )
                # 情绪趋势（纯规则，零 Token）
                from memory.relationship_growth import get_emotion_trend
                tl_entries = await self.relationship.timeline.get_recent(
                    context.platform, context.platform_user_id, days=7
                )
                emotion_trend = get_emotion_trend(tl_entries)
            except Exception as e:
                logger.debug(f"Relationship memory/emotion trend 加载失败: {e}")

        # 7. 构建系统 Prompt
        system_prompt = self._build_system_prompt(
            profile_context=mem_ctx.profile_context,
            memory_context=mem_ctx.memory_context,
            conversation_summary=summary_for_prompt,
            relationship_tone=relationship_tone,
            timeline_context=timeline_for_prompt,
            relationship_memory_context=relationship_memory_context,
            emotion_trend=emotion_trend,
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
            try:
                from archive.error_archive import record as err_record
                err_record("ai/core.py", f"LLM 调用失败: {e}")
            except Exception as e2:
                logger.debug(f"Error archive 记录失败: {e2}")
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
            _create_background_task(
                self._summarize_async(context, session)
            )

        # 10.6. Timeline 生成 + Growth Cycle（后台异步）
        if session.summary and len(session.summary) > 20:
            _create_background_task(
                self._generate_timeline_async(context, session.summary)
            )
            # Growth: Timeline >= 5 条时触发 Pattern Discovery + Merge
            _create_background_task(
                self._trigger_growth_if_needed(
                    context.platform, context.platform_user_id
                )
            )

        # 11. 异步提取 Profile（不阻塞本次回复）
        _create_background_task(
            self._extract_profile_async(context, reply)
        )

        # 对话归档（独立模块，不影响聊天流程）
        try:
            from archive.conversation_archive import save as archive_save
            archive_save(
                context.platform, context.platform_user_id,
                context.username or "未知",
                context.message, reply,
            )
        except Exception as e:
            logger.debug(f"对话归档失败: {e}")

        logger.info(
            f"[{context.platform}] 回复: "
            f"{context.username or context.platform_user_id} <- {reply[:50]}"
        )

        memory_updated = bool(mem_ctx.profile_context or mem_ctx.memory_context)
        return ChatResponse(content=reply, memory_updated=memory_updated)

    async def clear_session(self, platform: str, platform_user_id: str) -> None:
        """清除指定用户的对话历史缓存。

        委托 ai/session_manager.py（行为一致）。
        """
        self.sessions.clear(platform, platform_user_id)

    def get_history(self, platform: str, platform_user_id: str) -> list[dict[str, str]]:
        """获取对话历史（只读，从内存缓存）。

        委托 ai/session_manager.py（行为一致）。
        """
        return self.sessions.get_history(platform, platform_user_id)

    async def reload_history(self, platform: str, platform_user_id: str) -> list[dict[str, str]]:
        """从数据库重新加载对话历史。

        委托 ai/session_manager.py（行为一致）。
        """
        return await self.sessions.reload_from_db(platform, platform_user_id)

    # ================================================================
    # 内部方法
    # ================================================================

    def _format_user_message(self, context: ChatContext) -> str:
        """格式化发送给 LLM 的用户消息。

        委托 ai/message_formatter.py（行为一致）。
        """
        return format_user_message(context)

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
        """获取或创建用户会话（内存缓存）。

        委托 ai/session_manager.py（行为一致）。
        """
        return self.sessions.get_or_create(platform, platform_user_id)

    def _assemble_prompt_context(
        self,
        profile_context: str = "",
        memory_context: str = "",
        conversation_summary: str = "",
        relationship_tone: str = "",
        timeline_context: str = "",
        relationship_memory_context: str = "",
        emotion_trend: str = "",
        intent: Intent | None = None,
        world_state: WorldState | None = None,
        active_topics: ActiveTopics | None = None,
    ) -> PromptContext:
        """组装 PromptContext。

        位于 Step 6.5（关系理解注入）完成后、Step 7（构建 Prompt）前。
        仅做字段平铺，不渲染。

        Args:
            参数与 V3.8.1 的 _build_system_prompt() 完全一致。

        Returns:
            PromptContext（渲染所需全部上下文）
        """
        return PromptContext(
            profile_context=profile_context,
            memory_context=memory_context,
            conversation_summary=conversation_summary,
            relationship_tone=relationship_tone,
            timeline_context=timeline_context,
            relationship_memory_context=relationship_memory_context,
            emotion_trend=emotion_trend,
            world_state=world_state,
            active_topics=active_topics,
        )

    def _build_system_prompt(
        self,
        profile_context: str = "",
        memory_context: str = "",
        conversation_summary: str = "",
        relationship_tone: str = "",
        timeline_context: str = "",
        relationship_memory_context: str = "",
        emotion_trend: str = "",
        intent: Intent | None = None,
        world_state: WorldState | None = None,
        active_topics: ActiveTopics | None = None,
    ) -> str:
        """构建完整的 System Prompt（V3 选择性注入）。

        委托 PromptBuilder.build()（行为与 V3.8.1 逐字符一致）。

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
        ctx = self._assemble_prompt_context(
            profile_context=profile_context,
            memory_context=memory_context,
            conversation_summary=conversation_summary,
            relationship_tone=relationship_tone,
            timeline_context=timeline_context,
            relationship_memory_context=relationship_memory_context,
            emotion_trend=emotion_trend,
            intent=intent,
            world_state=world_state,
            active_topics=active_topics,
        )
        return self.prompt_builder.build(ctx)

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

    async def _trigger_growth_if_needed(
        self, platform: str, platform_user_id: str
    ) -> None:
        """如果 Timeline 积累 >= 5 条，触发 Growth Cycle（后台异步）。"""
        try:
            entries = await self.relationship.timeline.get_recent(
                platform, platform_user_id, days=30
            )
            if len(entries) >= 5:
                from memory.relationship_growth import RelationshipGrowth
                growth = RelationshipGrowth(self.memory.rel_memory_store)
                result = await growth.run_growth_cycle(
                    platform, platform_user_id, entries, self.provider,
                )
                if result["patterns"] > 0 or result["merged"] > 0:
                    logger.info(
                        f"Growth cycle: [{platform}:{platform_user_id}] "
                        f"patterns={result['patterns']} merged={result['merged']}"
                    )
        except Exception as e:
            logger.warning(f"Growth trigger 失败: {e}")

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
                _create_background_task(
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

        return (None, "")

    # ================================================================
    # 身份确认流程（Phase B2：委托 ai/identity.py）
    # ================================================================

    async def _has_pending_identity(
        self, platform: str, platform_user_id: str
    ) -> bool:
        """检查是否有待确认的身份记录。

        委托 ai/identity.py（行为一致）。
        """
        return await self.identity_flow.has_pending(platform, platform_user_id)

    @staticmethod
    def _looks_like_confirmation(message: str) -> bool:
        """检测消息是否为身份确认语句。

        委托 ai/identity.py（行为一致）。
        """
        return IdentityFlow.looks_like_confirmation(message)

    async def _resolve_pending_identity(
        self, platform: str, platform_user_id: str, confirm_msg: str
    ) -> None:
        """消费最近的 pending 身份记录 → confirmed → 写入 user_profiles。

        在 chat() 主流程中、build_prompt() 之前调用（Step 6a 同步完成）。
        委托 ai/identity.py（行为一致）。
        """
        await self.identity_flow.resolve_pending(
            platform, platform_user_id, confirm_msg
        )

    async def _create_pending_identity(
        self, context: ChatContext, intent: str
    ) -> None:
        """绕过 LLM + upsert，直接在 profile_history 创建 pending。

        委托 ai/identity.py（行为一致）。
        """
        await self.identity_flow.create_pending(context, intent)

    async def _get_confirmed_name(
        self, platform: str, platform_user_id: str
    ) -> tuple[str | None, str]:
        """获取用户姓名及其确认级别（V3.5 三级回退）。

        委托 ai/identity.py（行为一致）。
        """
        return await self.identity_flow.get_confirmed_name(
            platform, platform_user_id
        )

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
