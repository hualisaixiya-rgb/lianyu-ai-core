"""意图检测模块。

V4 Stage 0 Phase A1：从 ai/core.py 纯搬移，行为 100% 一致。

纯规则检测用户意图，零 Token。
判断顺序、关键词、枚举值均与迁移前完全一致。
"""

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
