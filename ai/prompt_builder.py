"""Prompt 构建模块。

V4 Stage 0 Phase A3：从 ai/core.py 纯搬移 _build_system_prompt，行为 100% 一致。

PromptBuilder 只做渲染，不知道变量来源。
PromptContext 的 12 个字段对应 prompt/templates/system.yaml 的 render 参数。
"""

from dataclasses import dataclass

from ai.world_tracker import get_time_context


@dataclass
class PromptContext:
    """Prompt 渲染所需的全部上下文。

    字段对应 prompt_manager.render("system", **kwargs) 的参数：
    - 原始输入（由 Orchestrator 组装）：
      profile_context / memory_context / conversation_summary / relationship_tone /
      timeline_context / relationship_memory_context / emotion_trend /
      world_state / active_topics
    - 内部生成（build 时填充，为空则自动生成）：
      identity / current_time / world_context
    """

    # ---- 原始输入 ----
    profile_context: str = ""
    memory_context: str = ""
    conversation_summary: str = ""
    relationship_tone: str = ""
    timeline_context: str = ""
    relationship_memory_context: str = ""
    emotion_trend: str = ""
    # world_state / active_topics 为对象（保持原逻辑：is_empty 判断 + to_prompt 转换）
    world_state: object | None = None
    active_topics: object | None = None

    # ---- 内部生成（build 时填充）----
    identity: str = ""
    current_time: str = ""
    world_context: str = ""


class PromptBuilder:
    """System Prompt 渲染器。

    依赖注入：prompt_manager（渲染模板）+ character（生成身份描述）。
    行为与 V3.8.1 的 _build_system_prompt() 逐字符一致。
    """

    def __init__(self, prompt_manager, character) -> None:
        """初始化。

        Args:
            prompt_manager: PromptManager 实例（渲染 system 模板）
            character: Character 实例（to_identity() 生成身份）
        """
        self.prompt_manager = prompt_manager
        self.character = character

    def build(self, ctx: PromptContext) -> str:
        """渲染 System Prompt。

        Args:
            ctx: 完整渲染上下文

        Returns:
            完整的 System Prompt 字符串
        """
        from utils.world_state import get_world_context

        # 内部生成字段（与 V3.8.1 一致：每次无条件生成）
        identity = ctx.identity or self.character.to_identity()
        world_context = ctx.world_context or get_world_context()
        time_context = ctx.current_time or get_time_context()

        # 摘要（仅非问候/身份确认时注入）
        summary_block = ""
        if ctx.conversation_summary:
            summary_block = f"【之前的对话】\n{ctx.conversation_summary}"

        # Timeline（仅回忆过去时注入）
        timeline_block = ""
        if ctx.timeline_context:
            timeline_block = f"【近期事件记录】\n{ctx.timeline_context}"

        # World State
        world_state_block = ""
        if ctx.world_state and not ctx.world_state.is_empty():
            world_state_block = ctx.world_state.to_prompt()

        # Active Topics
        topics_block = ""
        if ctx.active_topics and not ctx.active_topics.is_empty():
            topics_block = ctx.active_topics.to_prompt()

        return self.prompt_manager.render(
            "system",
            identity=identity,
            current_time=time_context,
            world_context=world_context,
            profile_context=ctx.profile_context,
            memory_context=ctx.memory_context,
            conversation_summary=summary_block,
            relationship_tone=ctx.relationship_tone,
            timeline_context=timeline_block,
            relationship_memory_context=ctx.relationship_memory_context,
            emotion_trend=ctx.emotion_trend,
            world_state_context=world_state_block,
            active_topics_context=topics_block,
        )
