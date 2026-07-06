"""Voice Style Controller —— 语音风格预处理层。

在 TTS 请求前对文本做轻量风格处理。
LLM 已经输出绘梨衣风格文本，VSC 只做必要清洗。
"""

import re

# 绘梨衣 prompt_text —— 短！GPT-SoVITS 会用这个文本的节奏做参考
ERI_PROMPT = "嗯。我在。"

# 情绪词弱化
WEAK_MAP = {"很": "有点", "非常": "有点", "十分": "有点", "特别": "有点"}


def apply_style(text: str, style: str = "eri") -> tuple[str, str]:
    """对 TTS 输入文本做轻量预处理。

    LLM 已输出绘梨衣风格文本，VSC 只做最小处理：
    1. 去掉括号动作描写
    2. 弱化极端情绪词
    3. 确保不长句（>30字才拆分）

    Args:
        text: LLM 输出（已有风格）
        style: "eri"

    Returns:
        (processed_text, prompt_text)
    """
    if style != "eri":
        return text, ""

    # 1. 去掉括号内容
    text = re.sub(r"（[^）]*）", "", text)
    text = re.sub(r"\([^)]*\)", "", text)

    # 2. 弱化情绪词
    for strong, weak in WEAK_MAP.items():
        text = text.replace(strong, weak)

    # 3. 只对超长句（>30字）做拆分，短句保持原样
    if len(text) > 30:
        text = _break_long(text, max_len=20)

    # 4. 清理多余空白
    text = text.strip()

    return text, ERI_PROMPT


def _break_long(text: str, max_len: int = 20) -> str:
    """只拆分超过 max_len 的句子。短句不动。"""
    parts = re.split(r"(?<=[。，……,])", text)
    result = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= max_len:
            result.append(p)
        else:
            # 机械切分
            for i in range(0, len(p), max_len):
                result.append(p[i:i + max_len])
    return "……".join(result)
