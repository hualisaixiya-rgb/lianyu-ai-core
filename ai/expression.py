"""表达层（V4 Stage 0.5 Expression Layer）。

只修复输出格式漂移，不改变人格、不改变内容语义。

真实 Telegram 观察到的 4 类漂移：
1. 句首省略号循环（…… 连续多行/多个）
2. 多行模板化（每句话一行，日常膨胀到 4+ 行）
3. 回复长度膨胀（日常 40~60 字，基线 8~11 字）
4. 句子级重复（同一句相邻重复）

设计原则：
- 所有规则对"正常输出"幂等（正常文本不被改写）——保证行为一致性测试 checksum 不破
- 规格按 daily / emotion / deep 三档，依据表达基线（docs/CHARACTER_EXPRESSION_BASELINE.md）
- 不调 LLM，纯规则，O(n)
"""

import re

from dataclasses import dataclass

# ----------------------------------------------------------------
# 表达规格
# ----------------------------------------------------------------


@dataclass(frozen=True)
class ExpressionSpec:
    """一种表达场景的格式规格。

    Attributes:
        name: 规格名（daily / emotion / deep）
        max_chars: 单条回复最大字符数（超长截断）
        max_lines: 最大行数（多行模板化压缩）
    """

    name: str
    max_chars: int
    max_lines: int


# 上限取表达基线（日常 8~11 字 / 情绪 19~23 / 深度 28）约 2~3 倍，
# 只拦"膨胀"，不压缩正常表达。
DAILY_SPEC = ExpressionSpec(name="daily", max_chars=30, max_lines=2)
EMOTION_SPEC = ExpressionSpec(name="emotion", max_chars=40, max_lines=3)
DEEP_SPEC = ExpressionSpec(name="deep", max_chars=60, max_lines=4)

# 深度词优先级高于情绪词（"还记得我们第一次…" 属于 deep 而非 emotion）
# 只收强深度词；"很久"等日常用语不触发（避免日常回复被放宽到 deep 档）
DEEP_KEYWORDS = (
    "记得", "回忆", "从前", "曾经", "如果", "为什么", "未来", "人生",
    "第一次", "永远", "世界", "梦", "想念", "愿意",
)
# 只收强情绪词；"温柔/笑"等日常词不触发（避免日常回复被放宽到 emotion 档）
EMOTION_KEYWORDS = (
    "难过", "开心", "生气", "哭", "爱", "担心", "委屈", "害怕",
    "孤独", "抱抱", "心疼", "好想", "舍不得",
)

# 句子切分符（重复检测用，不含 "…" —— 省略号是绘梨衣风格特征，不得切分）
_SENTENCE_END = "。！？!?"

# 截断边界查找符（含省略号，允许在省略号处优雅截断）
_TRUNCATE_END = _SENTENCE_END + "…"


# ----------------------------------------------------------------
# 规则 1：句首省略号规范化
# ----------------------------------------------------------------


def normalize_ellipsis_prefix(text: str) -> str:
    """句首省略号规范化。

    - 行首连续省略号（2+ 个）→ 压缩为 1 个（"……"）
    - 连续省略号行（2+ 行，如 "……\n……\n……"）→ 折叠为 1 行
    - 文本以省略号行开头且后接内容行 → 合并为 "……{内容}"（消除循环）

    省略号本身是绘梨衣风格特征，只合并堆叠，不删除。
    """
    lines = text.split("\n")
    folded: list[str] = []
    for line in lines:
        stripped = line.strip()
        # 行首连续省略号压缩为单个
        line = re.sub(r"^(?:(?:\.\.\.\.|…{2,}|。。+|\.{2,})\s*)+", "……", line)
        if stripped and re.fullmatch(r"(?:……|…{2,}|。。+|\.{2,})", stripped):
            # 省略号行：与上一个省略号行折叠
            if folded and re.fullmatch(r"(?:……|…{2,}|。。+|\.{2,})", folded[-1].strip()):
                continue
        folded.append(line)
    # 省略号行开头 + 内容行 → 合并
    if len(folded) >= 2 and re.fullmatch(r"……", folded[0].strip()):
        if folded[1].lstrip().startswith("……"):
            del folded[0]  # 下一行行首已有省略号，折叠行冗余，丢弃
        else:
            folded[0] = "……" + folded[1].lstrip()
            del folded[1]
    return "\n".join(folded)


# ----------------------------------------------------------------
# 规则 2：多行压缩
# ----------------------------------------------------------------


def collapse_lines(text: str, max_lines: int) -> str:
    """多行模板化压缩：空行删除 + 超限行以空格并入最后保留行。

    正常短回复（≤ max_lines 行）不被改写。
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[:max_lines]
    tail = " ".join(lines[max_lines:])
    kept[-1] = f"{kept[-1]} {tail}"
    return "\n".join(kept)


# ----------------------------------------------------------------
# 规则 3：相邻句重复检测
# ----------------------------------------------------------------


def _split_sentences(line: str) -> list[str]:
    """按句末标点切分单行（不含省略号），保留原始格式（含尾随空格）。

    例如 "我爱你。我爱你。" → ["我爱你。", "我爱你。"]
         "我等了好久。 眼泪要出来了。" → ["我等了好久。 ", "眼泪要出来了。"]
    """
    parts = re.split(r"([。！？!?]\s*)", line)
    sentences: list[str] = []
    buf = ""
    for part in parts:
        if not part:
            continue
        buf += part
        if part[0] in _SENTENCE_END:
            sentences.append(buf)
            buf = ""
    if buf.strip():
        sentences.append(buf)
    return sentences


def _strip_ellipsis_prefix(sentence: str) -> str:
    """去掉句子前导省略号/句点（比较用，不改变原文）。"""
    return sentence.lstrip("…。.")


def dedup_adjacent_sentences(text: str) -> str:
    """相邻句重复检测：相同句子只保留第一个，保留行结构。

    两级去重（比较时忽略前导省略号，见 _strip_ellipsis_prefix）：
    1. 行内：相邻相同句子（"我爱你。我爱你。" → "我爱你。"）
    2. 行间：整行与上一行相同（模板化逐行重复）

    只处理条内相邻重复；跨消息重复（27 秒内同一句再现）
    需要历史上下文，不在本层处理。
    """
    out_lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out_lines.append(line)  # 保留空行结构
            continue
        # 行内相邻去重（比较时忽略首尾空白与前导省略号）
        sents = _split_sentences(line)
        line_out: list[str] = []
        for sent in sents:
            key = _strip_ellipsis_prefix(sent.strip())
            if not (line_out and key == _strip_ellipsis_prefix(line_out[-1].strip())):
                line_out.append(sent)
        merged = "".join(line_out) or line
        # 行间去重（整行与上一行重复）
        if out_lines and _strip_ellipsis_prefix(merged.strip()) == _strip_ellipsis_prefix(out_lines[-1].strip()):
            continue
        out_lines.append(merged)
    return "\n".join(out_lines)


# ----------------------------------------------------------------
# 规则 4：最大长度保护
# ----------------------------------------------------------------


def truncate_to_max(text: str, max_chars: int) -> str:
    """超过 max_chars 时在句子边界截断并补省略号。

    截断位置：最后一个不超过 max_chars 的句子边界（。！？…），
    无边界则硬截断。截断后保证非空。
    """
    if len(text) <= max_chars:
        return text
    # 找 max_chars 内的最后一个句子边界（含省略号）
    cut = -1
    for i in range(max_chars - 1, 0, -1):
        if text[i - 1] in _TRUNCATE_END:
            cut = i
            break
    if cut < 1:
        cut = max_chars - 2
    result = text[:cut].rstrip()
    if result.endswith(("。", "！", "？", "!", "?", "…")):
        return result + "……"
    return result + "……"


# ----------------------------------------------------------------
# 规格推断 + 组合应用
# ----------------------------------------------------------------


def infer_spec(text: str) -> ExpressionSpec:
    """按回复内容推断表达规格（轻量关键词，不调 LLM）。

    优先级：deep > emotion > daily。
    """
    if any(k in text for k in DEEP_KEYWORDS):
        return DEEP_SPEC
    if any(k in text for k in EMOTION_KEYWORDS):
        return EMOTION_SPEC
    return DAILY_SPEC


def apply_expression(text: str, spec: ExpressionSpec) -> str:
    """按规格应用全部表达规则（顺序固定）。

    1. 句首省略号规范化
    2. 相邻句重复检测（必须在压缩前：压缩会把重复行并入上一行，
       导致行间去重失效）
    3. 多行压缩
    4. 最大长度保护（仅此规则可改变超长输出）
    """
    result = normalize_ellipsis_prefix(text)
    result = dedup_adjacent_sentences(result)
    result = collapse_lines(result, spec.max_lines)
    result = truncate_to_max(result, spec.max_chars)
    return result


def render_expression(text: str) -> str:
    """完整入口：推断规格 + 应用规则。"""
    return apply_expression(text, infer_spec(text))
