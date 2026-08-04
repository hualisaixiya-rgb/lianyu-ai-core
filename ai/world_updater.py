"""世界状态更新器。

V4 Stage 0 Phase B3：从 ai/core.py 提取 Step 5a/5b/5c 的 WorldState 调用编排。

只封装调用编排，不修改 world_tracker.py / Rule Engine：
- fallback 触发条件不变（needs_llm_fallback 原样调用）
- active_topics 更新时机不变（apply_rules 后、llm_fallback 后原顺序）
- LLM fallback 的 Prompt 与解析逻辑与 V3.8.1 一致
"""

from loguru import logger

from ai.world_tracker import (
    WorldState, ActiveTopics, ExpressionTracker,
    update_world_state, needs_llm_fallback, apply_rules,
)


class WorldStateUpdater:
    """Step 5a/5b/5c 调用编排。

    依赖注入：provider（LLM fallback 使用）。
    """

    def __init__(self, provider) -> None:
        """初始化。

        Args:
            provider: LLM Provider（仅 fallback 路径使用）
        """
        self.provider = provider

    def ensure_initialized(self, session) -> None:
        """Step 5：懒初始化 WorldState / ActiveTopics / ExpressionTracker。"""
        if session.world_state is None:
            session.world_state = WorldState()
        if session.active_topics is None:
            session.active_topics = ActiveTopics()
        if session.expression_tracker is None:
            session.expression_tracker = ExpressionTracker()

    def apply_rules(self, session, message: str) -> None:
        """Step 5a：Rule Engine 更新 World State（程序优先，零 Token）。"""
        rule_hits = apply_rules(message)
        if rule_hits:
            session.world_state = update_world_state(
                message, session.world_state
            )
            session._no_match_count = 0
        else:
            session._no_match_count += 1

    async def llm_fallback(self, session, message: str) -> None:
        """Step 5b：LLM Fallback（仅在 Rule 无法覆盖的复杂场景触发）。

        触发条件与 V3.8.1 完全一致（needs_llm_fallback）。
        """
        if needs_llm_fallback(
            message, session.world_state, session._no_match_count
        ):
            try:
                fallback = await self._llm_world_state_fallback(
                    message, session.world_state
                )
                if fallback:
                    for f, v in fallback.items():
                        if v and hasattr(session.world_state, f):
                            setattr(session.world_state, f, v)
                    session._no_match_count = 0
            except Exception as e:
                logger.debug(f"LLM world_state fallback 失败: {e}")

    def update_topics(self, session, message: str) -> None:
        """Step 5c：Active Topics 更新。"""
        session.active_topics.update(message)

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
        except Exception as e:
            logger.debug(f"LLM world_state fallback JSON 解析失败: {e}")
        return None
