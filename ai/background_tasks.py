"""后台任务模块。

V4 Stage 0 Phase C1：从 ai/core.py 纯搬移，行为 100% 一致。

- _create_background_task：create_task + wait_for(timeout=30) + 静默失败语义
- BackgroundTasks：4 个后台任务（摘要 / Timeline / Growth / Profile 提取）

并发策略（session._lock）：
- 锁只保护：session.summary 写入、session.messages 截断、session.pending_count 修改
- 锁不跨 await：LLM 调用前不加锁，LLM 返回后进入临界区
- 只读操作（batch 快照读取）不加锁
"""

import asyncio

from loguru import logger


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


class BackgroundTasks:
    """4 个后台任务。依赖通过构造注入。"""

    def __init__(self, memory, relationship, provider, identity_flow, should_extract) -> None:
        """初始化。

        Args:
            memory: MemoryManager 实例
            relationship: RelationshipStore 实例
            provider: LLM Provider 实例
            identity_flow: IdentityFlow 实例（create_pending）
            should_extract: callable（core 的 _should_extract 守卫）
        """
        self.memory = memory
        self.relationship = relationship
        self.provider = provider
        self.identity_flow = identity_flow
        self.should_extract = should_extract

    async def summarize(self, session) -> None:
        """异步滚动摘要：将窗口外的旧消息压缩为结构化摘要。

        取 session.messages 最旧的 8 条（锁外快照），调用 LLM 生成/合并摘要，
        LLM 返回后进入临界区：写 summary、截断 messages、重置 pending_count。
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
            # 临界区（session._lock 保护：summary 写入 / messages 截断 / pending_count 修改）
            async with session._lock:
                session.summary = new_summary
                session.messages = session.messages[8:]
                session.pending_count = 0
            logger.info(
                f"对话摘要更新: [{session.platform}:{session.platform_user_id}] "
                f"摘要={len(new_summary)}字 | 剩余消息={len(session.messages)}条"
            )
        except Exception as e:
            logger.warning(f"后台摘要失败: {e}")

    async def trigger_growth(
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

    async def generate_timeline(self, context, summary: str) -> None:
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

    async def extract_profile(self, context, ai_reply: str) -> None:
        """异步提取 Profile（后台运行，不影响回复速度）。

        identity intent → 不调 LLM，直接创建 pending。
        NAME_CHANGE_CONFIRM → 调 LLM 提取，正常 applied。
        """
        from memory.extractor import MemoryExtractor
        intent = MemoryExtractor._detect_profile_intent(context.message)

        # 身份声明 intent → 绕过 LLM，直接创建 pending
        if intent in ("NAME_INTRO", "NICKNAME_SET", "NAME_CHANGE_REQUEST"):
            await self.identity_flow.create_pending(
                context, intent,
            )
            return

        # 其他非身份场景 → 走正常的 _should_extract 守卫
        if not self.should_extract(context.message, ai_reply):
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
