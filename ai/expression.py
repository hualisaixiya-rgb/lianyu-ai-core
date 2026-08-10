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
# Stage 0.6 新增：轻量聊天档（打招呼/闲聊/简单互动）。
# 25 字/2 行为实验值（设计确认时指定 25-35 范围，避免复杂日常场景过度压缩），
# 最终参数以 8-08 真实归档校准为准。
CHAT_SPEC = ExpressionSpec(name="chat", max_chars=25, max_lines=2)

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

# Stage 0.6：用户消息高情绪词（用户表达真实情绪 → 合理深情回复保留，不降档）
USER_EMOTION_KEYWORDS = (
    "难过", "伤心", "哭", "害怕", "孤独", "委屈", "生气", "愤怒", "焦虑",
    "失眠", "睡不着", "生病", "难受", "心疼", "舍不得", "压力", "撑不住",
    "崩溃", "绝望", "痛苦", "无助", "疲惫", "好累", "很累", "太累", "累了",
    "想你了", "好想你", "很想你", "担忧", "担心", "不安", "烦死", "讨厌", "想哭",
)

# Stage 0.6：高浓度文学词（意象检测用）。
# 故意不含"星星/风/光"等日常可中性使用的词——避免误伤话题相关正常表达
# （生产数据中"那我是星星。每晚都在。"等是回应用户话题，非漂移）。
LITERARY_KEYWORDS = (
    "星辰", "港湾", "锚点", "归处", "银河", "月光", "星光", "黎明",
    "灯塔", "远山", "大海", "流星", "四季", "轮回", "永恒", "星河",
)

# Stage 0.6：轻量问候模式（用户打招呼 → chat 档）。
# "早"仅精确匹配整句（"早呀/早。"），避免误伤"早知道…"等。
_GREETING_PATTERNS = (
    r"^(你好|哈咯|哈喽|嗨|嗨喽|在吗|早安|早上好|下午好|晚上好|晚安|嘿嘿|哟|hello|hi|hey)",
    r"^早[呀啊]?$",
)

# 抽象意象排比模式（"是我的星辰，是我的港湾" 类堆叠）
_IMAGE_STACK_PATTERN = (
    r"(?:是我(?:的)?|是(?:我的)?)(?:星辰|港湾|锚点|归处|月光|星光|银河|灯塔|永恒|星河|梦|光|风|海|世界)"
)
# Stage 0.6 Calibration："像X，像Y，像Z"比喻排比（≥3 项连续，项长 ≤12）。
# 只收三连结构——"像你，像我"（2 项）与"像你一样"（1 项）是日常表达，不触发。
_LIKE_PARALLEL_PATTERN = re.compile(
    r"像[^，,。！？!?…\n]{1,12}[，,]\s*"
    r"像[^，,。！？!?…\n]{1,12}[，,]\s*"
    r"像[^，,。！？!?…\n]{1,12}"
)
# 高浓度承诺式（永远/无论… + 等/陪/守/留/爱…）。"一直"故意不收（轻度，不降档）
_COMMITMENT_PATTERN = re.compile(
    r"(?:永远|一辈子|此生|无论[^。！？]{0,6})[^。！？]{0,8}(?:等|陪|守|留|爱|记得|都在|不走|守护|不会离开)"
)

# 句子切分符（重复检测用，不含 "…" —— 省略号是绘梨衣风格特征，不得切分）
_SENTENCE_END = "。！？!?"

# 截断边界查找符（含省略号，允许在省略号处优雅截断）
_TRUNCATE_END = _SENTENCE_END + "…"


# ----------------------------------------------------------------
# 规则 1：句首省略号规范化
# ----------------------------------------------------------------


def normalize_ellipsis_prefix(text: str, max_prefix: int | None = None) -> str:
    """句首省略号规范化（Stage 0.6 增加强度档位）。

    - 行首连续省略号（2+ 个）→ 压缩为 1 个（"……"）——max_prefix=None/1 时
    - max_prefix=0（chat 档）：删除句首省略号（"……嗯，你好。" → "嗯，你好。"），
      孤立省略号行（"……" 单行）直接丢弃
    - max_prefix=1（daily 档）：句首省略号最多保留 1 次（超出堆叠压缩）
    - max_prefix=None（emotion/deep 档，默认）：保留省略号风格（同 1，只合并堆叠）
    - 连续省略号行（2+ 行）→ 折叠为 1 行；省略号行开头 + 内容行 → 合并

    Stage 0.5 设计原则"省略号是风格特征，只合并不删除"；
    Stage 0.6 调整为"省略号是情绪工具"——轻量场景删除（max_prefix=0），
    情感场景保留（max_prefix=None）。
    """
    lines = text.split("\n")
    folded: list[str] = []
    for line in lines:
        stripped = line.strip()
        is_ellipsis_line = bool(stripped) and re.fullmatch(
            r"(?:……|…{2,}|。。+|\.{2,})", stripped
        )
        # 行首省略号压缩（max_prefix=0 → 删除；否则 → 单个）
        if max_prefix == 0:
            line = re.sub(r"^(?:(?:\.\.\.\.|…{2,}|。。+|\.{2,})\s*)+", "", line)
        else:
            line = re.sub(r"^(?:(?:\.\.\.\.|…{2,}|。。+|\.{2,})\s*)+", "……", line)
        if is_ellipsis_line:
            if max_prefix == 0:
                continue  # 孤立省略号行：轻量档直接丢弃
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
# Stage 0.6：场景判断（问候 / 高情绪 / 文学强度）
# ----------------------------------------------------------------


def is_greeting(user_msg: str) -> bool:
    """用户消息是否为轻量问候（打招呼 → chat 档）。"""
    m = user_msg.strip()
    return any(re.match(p, m) for p in _GREETING_PATTERNS)


def is_high_emotion(user_msg: str) -> bool:
    """用户消息是否含高情绪表达（难过/哭/想你了… → 保留深情表达）。"""
    return any(k in user_msg for k in USER_EMOTION_KEYWORDS)


def detect_literary_intensity(text: str, detection_text: str | None = None) -> bool:
    """文学强度检测（三条规则任一命中 → 高浓度）。

    1. 文学词 + 情绪词组合（"我好难过……你是我的星辰"）
    2. 抽象意象连续堆叠（"是我的星辰，是我的港湾" 排比 ≥2；
       或同句意象间距 ≤15 字；或"像X，像Y，像Z"比喻排比 ≥3 项）
    3. 高浓度承诺式表达（"永远/无论… + 等/陪/守"）

    detection_text: 可选，仅用于检测的归一化文本（Stage 0.6 Calibration）。
      调用方传入 text.replace("\\n", " ") 时，跨行意象（行尾意象 + 下行意象）
      可被间距/排比规则检测；None 时用原 text。**不影响展示文本格式**。

    防误伤设计：
    - "星星/风/光"等日常中性词不在意象表（话题相关正常表达不触发）
    - "一直"不在承诺触发词（"我会一直陪着你" 轻度，不降档）
    - "像"排比只收 ≥3 项连续结构（"像你，像我"等 2 项日常表达不触发）
    """
    d = text if detection_text is None else detection_text
    # 规则 1：文学词 + 情绪词组合
    if any(k in d for k in LITERARY_KEYWORDS) and any(k in d for k in EMOTION_KEYWORDS):
        return True
    # 规则 2：抽象意象堆叠
    if len(re.findall(_IMAGE_STACK_PATTERN, d)) >= 2:
        return True
    positions = sorted(m.start() for m in re.finditer(
        r"(星辰|港湾|锚点|归处|银河|月光|星光|永恒|星河|灯塔)", d
    ))
    # 间距阈值 25：允许跨行意象（行尾意象 + 下行意象）。
    # Calibration 依据：8-08 #3 "锚点→港湾" 跨行间距实测 23（原 15 漏检）；
    # 7 月生产基线 287 条含 ≥2 意象词的消息为 0 → 放宽零新增命中（零误伤）。
    if len(positions) >= 2 and any(b - a <= 25 for a, b in zip(positions, positions[1:])):
        return True
    # 规则 2c（Calibration 新增）："像X，像Y，像Z"比喻排比
    if _LIKE_PARALLEL_PATTERN.search(d):
        return True
    # 规则 3：高浓度承诺式
    if _COMMITMENT_PATTERN.search(d):
        return True
    return False


# ----------------------------------------------------------------
# 规格推断 + 组合应用
# ----------------------------------------------------------------


def _keyword_spec(text: str) -> ExpressionSpec:
    """按回复关键词推断规格（无上下文）：deep > emotion > daily。"""
    if any(k in text for k in DEEP_KEYWORDS):
        return DEEP_SPEC
    if any(k in text for k in EMOTION_KEYWORDS):
        return EMOTION_SPEC
    return DAILY_SPEC


def infer_spec(text: str, user_msg: str | None = None) -> ExpressionSpec:
    """按回复内容 + 用户消息上下文推断表达规格。

    Stage 0.6 上下文感知（使表达强度匹配聊天场景）：
    1. 用户消息高情绪（难过/哭/想你了…）→ 保留关键词档，不降档
       —— 用户高情绪输入 → 合理深情回复：保留
    2. 用户消息轻量问候（你好/哈咯/在吗…）→ chat 档（优先于关键词档）
       —— 普通输入 → 深情回复：压缩为轻量
    3. 无上下文 / 普通输入：关键词推断；回复文学强度高且落 deep 档
       → 降 emotion 档（收紧呈现峰值）
       —— 普通用户输入 → 高浓度文学回复：降档

    优先级：高情绪 > 问候 > 关键词（+ deep 文学降档）。
    不传 user_msg → 行为与 Stage 0.5 完全一致（向后兼容）。
    """
    if user_msg:
        um = user_msg.strip()
        if is_high_emotion(um):
            return _keyword_spec(text)
        if is_greeting(um):
            return CHAT_SPEC
    spec = _keyword_spec(text)
    if spec.name == "deep" and detect_literary_intensity(text, text.replace("\n", " ")):
        return EMOTION_SPEC
    return spec


def apply_expression(text: str, spec: ExpressionSpec) -> str:
    """按规格应用全部表达规则（顺序固定）。

    1. 句首省略号规范化（chat 档删句首省略号+孤立省略号行；
       daily 档保留 1 次；emotion/deep 保留风格）
    2. 相邻句重复检测（必须在压缩前：压缩会把重复行并入上一行，
       导致行间去重失效）
    3. 多行压缩
    4. 最大长度保护（仅此规则可改变超长输出）
    """
    max_prefix = 0 if spec.name == "chat" else 1
    result = normalize_ellipsis_prefix(text, max_prefix)
    result = dedup_adjacent_sentences(result)
    result = collapse_lines(result, spec.max_lines)
    result = truncate_to_max(result, spec.max_chars)
    return result


def render_expression(text: str, user_msg: str | None = None) -> str:
    """完整入口：推断规格（含用户消息上下文）+ 应用规则。"""
    return apply_expression(text, infer_spec(text, user_msg))
