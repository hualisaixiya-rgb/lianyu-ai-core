"""意图检测模块。

V4 Stage 0 Phase A1：从 ai/core.py 纯搬移，行为 100% 一致。

纯规则检测用户意图，零 Token。
判断顺序、关键词、枚举值均与迁移前完全一致。
"""

from dataclasses import dataclass
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


# ================================================================
# V4 Emotion Regulation Layer：情绪强度检测（2026-08-11）
# 纯规则、零 Token、零外部依赖，与 detect_intent 同风格。
# 数据层与 Prompt 层解耦：本模块只返回强度档与命中词，
# 场景注入文本由 PromptBuilder 按档位查表生成（见 ai/prompt_builder.py）。
# ================================================================

# L1 轻度（不触发场景注入）：日常情绪表达
EMOTION_L1_KEYWORDS = (
    "难过", "伤心", "委屈", "生气", "愤怒", "焦虑", "失眠", "睡不着",
    "难受", "心疼", "舍不得", "压力", "疲惫", "好累", "很累", "太累",
    "累了", "想你了", "好想你", "很想你", "担忧", "担心", "不安", "烦死",
    "讨厌", "想哭", "生病", "不开心", "烦", "累",
)

# L2 高情绪（触发 HIGH_EMOTION 场景注入）
EMOTION_L2_KEYWORDS = (
    "害怕", "恐惧", "孤独", "崩溃", "绝望", "痛苦", "无助", "撑不住",
    "哭", "心碎", "心累", "没力气", "撑不下去", "坚持不住", "受不了",
)

# L3 危机（触发 CRISIS 场景注入；检查顺序优先，覆盖 L2。
# "撑不下去了" 含 L2 子串"撑不下去"——L3 先检查保证危机语义优先）
EMOTION_L3_KEYWORDS = (
    "想死", "自杀", "不想活", "活不下去", "活着没意思", "伤害自己",
    "割腕", "跳楼", "遗书", "告别世界", "撑不下去了",
)

_SOURCE_USER_MESSAGE = "user_message"


@dataclass(frozen=True)
class EmotionState:
    """一次情绪检测的结果（纯数据，零逻辑）。

    Attributes:
        level: 情绪强度档（0=无 / 1=轻度 / 2=高情绪 / 3=危机）
        source: 检测来源（当前为 "user_message"；未来可扩展会话级，见设计文档 §3）
        matched: 命中档位命中的关键词（校准/审计用，不注入 Prompt）
    """

    level: int
    source: str
    matched: tuple[str, ...]


def detect_emotion_state(user_msg: str) -> EmotionState:
    """检测用户消息的情绪强度（纯规则，零 Token）。

    分档 L0（无情绪）/ L1（轻度）/ L2（高情绪）/ L3（危机），
    L3 优先覆盖 L2（检查顺序 L3 → L2 → L1）。

    Args:
        user_msg: 用户消息原文

    Returns:
        EmotionState：强度档 + 来源 + 命中词（L0 时 matched 为空）
    """
    msg = user_msg.strip()
    if not msg:
        return EmotionState(level=0, source=_SOURCE_USER_MESSAGE, matched=())
    for level, keywords in (
        (3, EMOTION_L3_KEYWORDS),
        (2, EMOTION_L2_KEYWORDS),
        (1, EMOTION_L1_KEYWORDS),
    ):
        hit = tuple(k for k in keywords if k in msg)
        if hit:
            return EmotionState(level=level, source=_SOURCE_USER_MESSAGE, matched=hit)
    return EmotionState(level=0, source=_SOURCE_USER_MESSAGE, matched=())
