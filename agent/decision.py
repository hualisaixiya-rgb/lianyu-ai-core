"""决策引擎 —— 判断是否发送主动消息。

核心逻辑：概率 + 时间 + 关系值 + 冷却 + 上限。
"""

import random
from datetime import datetime, timezone

from agent.state import AgentState, AgentStateRepository
from loguru import logger


def minutes_since(dt: datetime) -> float:
    """计算距离现在多少分钟。"""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 60.0


def hours_since(dt: datetime) -> float:
    """计算距离现在多少小时。"""
    return minutes_since(dt) / 60.0


def should_send(state: AgentState) -> bool:
    """判断是否应该发送主动消息。

    实现概率决策：
    - 基础概率 3%
    - 用户最近 60 分钟内活跃 → +15%
    - 超过 6 小时未发消息 → +10%
    - bond 越高 → 概率越高（bond × 0.25）
    - 冷却期（30 分钟内发过）→ 禁止
    - 每日上限 → 禁止
    - 夜间降频（23:00-08:00）→ 概率 × 0.3

    Args:
        state: Agent 状态

    Returns:
        是否发送
    """
    # 冷却检查
    mins = minutes_since(state.last_bot_message_time)
    if mins < AgentStateRepository.COOLDOWN_MINUTES:
        logger.debug(f"冷却中: {mins:.0f}min < {AgentStateRepository.COOLDOWN_MINUTES}min")
        return False

    # 每日上限检查
    if state.daily_message_count >= AgentStateRepository.DAILY_MAX:
        logger.debug(f"已达每日上限: {state.daily_message_count}")
        return False

    # 基础概率
    prob = 0.03

    # 用户最近活跃
    if minutes_since(state.last_user_active_time) < 60:
        prob += 0.15

    # 长时间未发消息
    if hours_since(state.last_bot_message_time) > 6:
        prob += 0.10

    # bond 影响
    prob += state.bond * 0.25

    # 夜间降频
    hour = datetime.now().hour
    if hour >= 23 or hour < 8:
        prob *= 0.3

    # 随机决策
    roll = random.random()
    logger.debug(
        f"决策: prob={prob:.3f} roll={roll:.3f} "
        f"bond={state.bond:.2f} count={state.daily_message_count}"
    )
    return roll < prob
