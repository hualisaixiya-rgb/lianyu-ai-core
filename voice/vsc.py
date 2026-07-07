"""Voice Style Controller —— 语音风格预处理层（安全模式）。

只做文本清洗，不重写语义。
"""

import re


def apply_style(text: str, style: str = "eri") -> tuple[str, str]:
    """对 TTS 输入做安全预处理。

    只做：
    1. 去掉括号动作描写
    2. prompt_text 留空（让 GPT-SoVITS 从参考音频自动检测）

    不做：添加省略号、拆句、改词、重写。

    Args:
        text: LLM 输出（已有风格）
        style: "eri"

    Returns:
        (processed_text, prompt_text)
    """
    if style != "eri":
        return text, ""

    # 只去掉括号内容，其他全部保留
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = text.strip()

    # prompt_text 留空 —— GPT-SoVITS 自动从参考音频推导韵律
    return text, ""
