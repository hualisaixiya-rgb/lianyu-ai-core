"""Voice Style Controller —— 语音风格预处理层。

在 TTS 请求前对文本做角色风格化处理。
不修改 GPT-SoVITS 服务端，只做输入层预处理。

用法：
    from voice.vsc import apply_style
    text, prompt = apply_style("你好，我今天很开心！", "eri")
"""

import re


# 绘梨衣风格的 prompt_text（固定模板）
ERI_PROMPT = (
    "说话很慢，有明显停顿，语气偏弱，不稳定，"
    "有轻微犹豫感，像刚开口说话的人，不连续表达情绪。"
)

# 情绪弱化映射
EMOTION_WEAK_MAP = {
    "很": "有点",
    "非常": "稍微",
    "十分": "有点",
    "特别": "有点",
    "太": "有点",
    "超级": "有点",
    "极其": "有点",
}


def apply_style(text: str, style: str = "eri") -> tuple[str, str]:
    """对 TTS 输入文本做风格预处理。

    Args:
        text: LLM 原始输出文本
        style: 风格名，目前支持 "eri"

    Returns:
        (processed_text, prompt_text) 元组
    """
    if style != "eri":
        return text, ""

    processed = _apply_eri(text)
    return processed, ERI_PROMPT


def _apply_eri(text: str) -> str:
    """绘梨衣风格处理。

    步骤：
    1. 情绪弱化：很/非常 → 有点/稍微
    2. 感叹号 → 省略号
    3. 问号 → 省略号
    4. 句号 → 省略号
    5. 拆长句为短句（≤15字），用"……"连接
    6. 去掉多余空白
    """
    # 1. 情绪弱化
    for strong, weak in EMOTION_WEAK_MAP.items():
        text = text.replace(strong, weak)

    # 2-4. 标点替换
    text = text.replace("！", "……")
    text = text.replace("!", "……")
    text = text.replace("？", "……")
    text = text.replace("?", "……")
    text = text.replace("。", "……")
    text = text.replace(".", "……")

    # 5. 拆长句
    sentences = _split_short(text, max_len=15)

    # 6. 用"……"连接，首尾加停顿
    result = "……".join(s.strip() for s in sentences if s.strip())
    result = "……" + result + "……"

    # 清理多余的连续省略号
    result = re.sub(r"……{2,}", "……", result)

    return result


def _split_short(text: str, max_len: int = 15) -> list[str]:
    """将文本拆为短句，每句不超过 max_len 字。

    优先按标点拆分，超长的句子按逗号或字数切分。

    Args:
        text: 输入文本
        max_len: 每句最大字数

    Returns:
        短句列表
    """
    # 先按标点预拆分
    raw_parts = re.split(r"[，,……、\s]+", text)
    result = []

    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_len:
            result.append(part)
        else:
            # 按 max_len 机械切分
            for i in range(0, len(part), max_len):
                chunk = part[i:i + max_len]
                result.append(chunk)

    return result
