"""TTS 文本净化层。

清理 LLM 输出中的括号内容，避免 TTS 朗读动作描写。
不影响 AICore / Prompt / Memory / DB 逻辑。
"""

import re


def clean_for_tts(text: str) -> str:
    """清洗文本，移除所有括号内容，使其适合 TTS 朗读。

    处理规则：
    - 删除中文全角括号及内容：（...）
    - 删除英文半角括号及内容：(...)
    - 删除多余空白，保留基本标点
    - 不修改句子结构，不重写内容

    Args:
        text: LLM 原始输出

    Returns:
        清洗后的纯朗读文本

    Examples:
        >>> clean_for_tts("（微微一笑）你好呀")
        '你好呀'
        >>> clean_for_tts("(looking down) Hello there")
        'Hello there'
        >>> clean_for_tts("你好（笑）……今天天气不错")
        '你好……今天天气不错'
    """
    # 1. 删除中文全角括号及内容
    text = re.sub(r"（[^）]*）", "", text)

    # 2. 删除英文半角括号及内容
    text = re.sub(r"\([^)]*\)", "", text)

    # 3. 清理多余空格（多个空格 → 一个）
    text = re.sub(r" {2,}", " ", text)

    # 4. 清理括号残留可能造成的多余标点（如 "，。" → "。"）
    text = re.sub(r"[，,]\s*[。.]", "。", text)

    # 5. 去掉首尾空白
    text = text.strip()

    return text
