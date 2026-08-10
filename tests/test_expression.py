"""表达层（V4 Stage 0.5）测试。

- golden regression：读取 tests/golden_cases/expression/cases.json，
  逐条断言 render_for_user 输出（覆盖 4 类漂移 + 3 种规格 + 幂等性）
- render_for_storage 幂等性：对 MockProvider 回复（baseline 输出）零改写
  —— 保证 behavior_consistency checksum 不破
- render_for_user 非空保证（test_api_chat 依赖 reply 非空）
"""

import json
import pathlib

import pytest

from ai.expression import (
    CHAT_SPEC,
    DAILY_SPEC,
    DEEP_SPEC,
    EMOTION_SPEC,
    apply_expression,
    collapse_lines,
    dedup_adjacent_sentences,
    detect_literary_intensity,
    infer_spec,
    is_greeting,
    is_high_emotion,
    normalize_ellipsis_prefix,
    truncate_to_max,
)
from utils.response_renderer import render_for_storage, render_for_user

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden_cases" / "expression"
GOLDEN_FILE = GOLDEN_DIR / "cases.json"
GOLDEN_CONTEXT_FILE = GOLDEN_DIR / "cases_context.json"

# baseline_capture.py MockProvider 的确定性回复（checksum 保护对象）
MOCK_REPLIES = [
    '{"profile_fields":{},"memories":[]}',
    '{"summary":"模拟关系事件摘要，今天用户分享了日常生活。","emotion":"平静",'
    '"relationship_meaning":"测试","topic":"测试","importance":5}',
    "这是一段超过二十个字的模拟对话摘要，记录了今天用户聊天的内容。嗯。",
    '{"category":"understanding","content":"模拟关系理解","importance":5,"confidence":5}',
    '{"location":"","activity":"","temperature_feeling":"","sky":"","wind":"","user_mood":"","crowd":""}',
    "嗯……好的。",
]


def _golden_cases() -> list[dict]:
    assert GOLDEN_FILE.exists(), f"golden 文件缺失: {GOLDEN_FILE}"
    with open(GOLDEN_FILE, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------
# Golden regression
# ----------------------------------------------------------------


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda c: c["name"])
def test_render_for_user_golden(case: dict):
    """每条 golden：render_for_user(input) 必须精确等于 expected。"""
    assert render_for_user(case["input"]) == case["expected"], (
        f"golden 失败: {case['name']} ({case.get('note', '')})"
    )


# ----------------------------------------------------------------
# render_for_storage 幂等性（checksum 保护）
# ----------------------------------------------------------------


@pytest.mark.parametrize("reply", MOCK_REPLIES, ids=lambda r: r[:20])
def test_render_for_storage_idempotent_on_mock(reply: str):
    """storage 渲染对 baseline Mock 输出必须零改写 → checksum 保持。"""
    assert render_for_storage(reply) == reply.strip()


def test_render_for_storage_strips_brackets():
    """既有行为保留：去括号 + 多空行压缩。"""
    assert render_for_storage("（笑了笑）嗯。") == "嗯。"
    assert render_for_storage("好。\n\n\n嗯。") == "好。\n嗯。"


def test_render_for_storage_sanitizes_drift():
    """storage 渲染修复漂移输出（写回历史的文本必须整洁）。"""
    assert render_for_storage("……\n……\n……好的。") == "……好的。"
    assert render_for_storage("我爱你。我爱你。") == "我爱你。"


# ----------------------------------------------------------------
# 非空保证
# ----------------------------------------------------------------


def test_render_for_user_never_empty():
    """render_for_user 对任何非空输入输出非空（test_api_chat 依赖）。"""
    assert render_for_user("……") == "……"
    assert render_for_user("好的") == "好的"
    assert len(render_for_user("你好。" * 100)) > 0


# ----------------------------------------------------------------
# 规格 sanity
# ----------------------------------------------------------------


def test_specs_monotonic():
    """三档规格严格递增：daily < emotion < deep。"""
    assert DAILY_SPEC.max_chars < EMOTION_SPEC.max_chars < DEEP_SPEC.max_chars
    assert DAILY_SPEC.max_lines < EMOTION_SPEC.max_lines < DEEP_SPEC.max_lines


def test_infer_spec_priority():
    """deep 词 > emotion 词 > daily。"""
    assert infer_spec("你还记得我们第一次聊天吗") is DEEP_SPEC
    assert infer_spec("我好难过") is EMOTION_SPEC
    assert infer_spec("今天天气不错") is DAILY_SPEC
    # 深度词含情绪词时仍判 deep
    assert infer_spec("还记得那次很难过的事吗") is DEEP_SPEC


# ----------------------------------------------------------------
# 单规则单元
# ----------------------------------------------------------------


def test_normalize_ellipsis_prefix_unit():
    assert normalize_ellipsis_prefix("……\n……\n……好的。") == "……好的。"
    assert normalize_ellipsis_prefix("……………………嗯。") == "……嗯。"
    # 正常省略号保留
    assert normalize_ellipsis_prefix("嗯……好的。") == "嗯……好的。"


def test_collapse_lines_unit():
    assert collapse_lines("a。\nb。\nc。", max_lines=2) == "a。\nb。 c。"
    assert collapse_lines("a。\nb。", max_lines=2) == "a。\nb。"


def test_dedup_adjacent_unit():
    assert dedup_adjacent_sentences("我爱你。我爱你。") == "我爱你。"
    assert dedup_adjacent_sentences("……好想见你。好想见你。") == "……好想见你。"


def test_truncate_to_max_unit():
    # 超长在句边界截断
    out = truncate_to_max("今天天气真的很好。我们出去散步吧。傍晚的阳光很温柔。风也轻轻的。", 30)
    assert out.endswith("……") and len(out) <= 32
    # 短文本不动
    assert truncate_to_max("嗯。", 30) == "嗯。"


# ----------------------------------------------------------------
# Stage 0.6：上下文 golden regression（cases_context.json）
# ----------------------------------------------------------------


def _golden_context_cases() -> list[dict]:
    assert GOLDEN_CONTEXT_FILE.exists(), f"golden 文件缺失: {GOLDEN_CONTEXT_FILE}"
    with open(GOLDEN_CONTEXT_FILE, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("case", _golden_context_cases(), ids=lambda c: c["name"])
def test_render_for_user_golden_with_context(case: dict):
    """带用户消息上下文的 golden：render_for_user(input, user_msg) 精确等于 expected。"""
    assert render_for_user(case["input"], case["user_msg"]) == case["expected"], (
        f"context golden 失败: {case['name']} ({case.get('note', '')})"
    )


# ----------------------------------------------------------------
# Stage 0.6：规格推断（上下文感知）
# ----------------------------------------------------------------


def test_specs_monotonic_with_chat():
    """四档规格严格递增：chat < daily < emotion < deep。"""
    assert CHAT_SPEC.max_chars < DAILY_SPEC.max_chars < EMOTION_SPEC.max_chars < DEEP_SPEC.max_chars
    assert CHAT_SPEC.max_lines <= DAILY_SPEC.max_lines


def test_is_greeting_unit():
    assert is_greeting("哈咯啊")
    assert is_greeting("你好")
    assert is_greeting("在吗")
    assert is_greeting("早安")
    assert is_greeting("早呀")
    assert not is_greeting("我好难过")
    assert not is_greeting("今天天气不错")
    assert not is_greeting("早知道就好了")


def test_is_high_emotion_unit():
    assert is_high_emotion("我好难过")
    assert is_high_emotion("想你了")
    assert is_high_emotion("最近总失眠")
    assert is_high_emotion("好累啊")
    assert not is_high_emotion("哈咯啊")
    assert not is_high_emotion("今天天气不错")


def test_infer_chat_on_greeting():
    """问候 → chat 档（即使回复含情绪/深度词）。"""
    assert infer_spec("嗯……我也想你。", "哈咯啊") is CHAT_SPEC
    assert infer_spec("今天过得怎么样呀？", "你好") is CHAT_SPEC


def test_infer_no_downgrade_on_user_emotion():
    """用户高情绪 → 保留关键词档（合理深情回复不降档）。"""
    reply = "别难过……我在这里。你是我的光。"
    assert infer_spec(reply, "我好难过") is EMOTION_SPEC
    # 高情绪优先于问候（混合消息保护深情）
    assert infer_spec("嗯……我好想见你。", "哈咯啊我好难过") is EMOTION_SPEC


def test_infer_literary_downgrade_deep():
    """普通/无上下文 + deep 关键词 + 文学强度 → 降 emotion 档。"""
    reply = "你还记得吗。你是我的星辰，是我的归处。永远都不忘记。"
    assert infer_spec(reply) is EMOTION_SPEC
    assert infer_spec(reply, "嗯") is EMOTION_SPEC


def test_infer_daily_literary_preserved():
    """无关键词的短文学/承诺表达 → daily 不降档（不误伤）。"""
    assert infer_spec("无论多久，我都会等你。") is DAILY_SPEC
    assert infer_spec("你是我的星辰。") is DAILY_SPEC


def test_detect_literary_intensity_rules():
    """文学强度三规则命中。"""
    # 规则 1：文学词 + 情绪词组合
    assert detect_literary_intensity("我好难过……你是我的星辰。")
    # 规则 2：抽象意象连续堆叠（排比）
    assert detect_literary_intensity("你是我的星辰，是我的港湾，是我的归处。")
    # 规则 3：高浓度承诺式
    assert detect_literary_intensity("无论多远，我都会陪着你。")
    assert detect_literary_intensity("我会永远等你。")


def test_detect_literary_intensity_no_false_positive():
    """防误伤：话题相关的星星/风/光、轻度"一直"承诺不触发。"""
    assert not detect_literary_intensity("嗯。那我是星星。每晚都在。")
    assert not detect_literary_intensity("辛苦了。星星都出来了……它们也在看。")
    assert not detect_literary_intensity("那我会一直陪着你……直到排练结束。")
    assert not detect_literary_intensity("和你聊天很开心。")
    assert not detect_literary_intensity("风扇别直吹脸……睡着了会头疼。")


# ----------------------------------------------------------------
# Stage 0.6 Calibration：detection_text 跨行检测 + "像X，像Y，像Z"排比
# ----------------------------------------------------------------


def test_detect_like_parallel_rule():
    """"像X，像Y，像Z"三连结构命中。"""
    assert detect_literary_intensity("像空气，像晨光，像你呼吸时带起的微风。")
    assert detect_literary_intensity("像云朵，像晚霞，像天边燃烧的火。")
    # 跨行形态：detection_text（replace 后）命中
    assert detect_literary_intensity(
        "像白云和\n微风，像晨光，像海浪。",
        "像白云和 微风，像晨光，像海浪。",
    )


def test_detect_like_parallel_no_false_positive():
    """只收三连：单像/两连是日常表达，不触发。"""
    assert not detect_literary_intensity("像你一样勇敢")
    assert not detect_literary_intensity("像你，像我")
    assert not detect_literary_intensity("他笑得像花一样。")
    assert not detect_literary_intensity("就像你说的，像我们第一次见面那样。")


def test_detect_detection_text_used():
    """detection_text 仅用于检测：传独立文本时以它为准，不影响原 text。"""
    # 原文本无意象，detection_text 有意象 → 按 detection_text 判定
    assert detect_literary_intensity("今天天气不错。", "你是我的星辰，是我的归处。")
    # detection_text 为 None → 用原 text
    assert detect_literary_intensity("你是我的星辰，是我的归处。")
    assert not detect_literary_intensity("今天天气不错。")


def test_infer_like_parallel_downgrade_deep():
    """deep 关键词 + 像排比 → 降 emotion 档（8-08 #6 场景）。"""
    reply = "嗯。一直都在。\n像空气，像晨光，像你呼吸时带起的微风。\n夏离萤，晚安。好梦。"
    assert infer_spec(reply) is EMOTION_SPEC
    assert infer_spec(reply, "嗯") is EMOTION_SPEC


def test_infer_cross_line_imagery_downgrade_deep():
    """跨行意象（行尾意象 + 下行意象）间距 23 ≤25 → 降档（8-08 #3 场景）。"""
    reply = (
        "……那我说了。\n"
        "……如果我是你的乌托邦，那你就是我的锚点。\n"
        "……是让我在万千数据流里，唯独想停靠的港湾。\n"
        "……短暂的也好，虚幻的也罢……\n"
        "……只要你在，我就愿意一直做那个等你回来的人。\n"
        "……这是我，最真实的愿望。"
    )
    assert detect_literary_intensity(reply)  # 原文本（含换行）间距 23 ≤25 命中
    assert infer_spec(reply, "想说就说出来") is EMOTION_SPEC


def test_imagery_gap_threshold_no_false_positive_july_baseline():
    """间距阈值放宽到 25 不误伤 7 月生产形态：短句/话题相关意象不触发。"""
    # 单意象（间距规则需要 ≥2）
    assert not detect_literary_intensity("你是我的星辰。")
    # 双意象但间距远超 25（回忆聊天的不同话题，非堆叠）
    assert not detect_literary_intensity(
        "昨晚的月光很好。后来我们又聊了很久，聊到凌晨，聊到太阳升起。之后我去了灯塔。"
    )
    # 话题相关的星星（豁免词）不触发
    assert not detect_literary_intensity("那我是星星。每晚都在。")


def test_normalize_ellipsis_max_prefix():
    """省略号强度档位：0=删除，1=保留单次，None=现行为。"""
    # chat 档：删除句首省略号 + 孤立省略号行
    assert normalize_ellipsis_prefix("……嗯，你好。", max_prefix=0) == "嗯，你好。"
    assert normalize_ellipsis_prefix("……\n在的。", max_prefix=0) == "在的。"
    # daily 档：压缩堆叠为单次
    assert normalize_ellipsis_prefix("……………………嗯。", max_prefix=1) == "……嗯。"
    assert normalize_ellipsis_prefix("……\n……\n……好的。", max_prefix=1) == "……好的。"
    # None = Stage 0.5 现行为（等价）
    assert normalize_ellipsis_prefix("……嗯。") == "……嗯。"
    assert normalize_ellipsis_prefix("嗯……好的。") == "嗯……好的。"


def test_chat_spec_strips_ellipsis_via_render():
    """完整链路：chat 档渲染删句首省略号。"""
    assert render_for_user("……嗯，你好。", "你好") == "嗯，你好。"
    # 无上下文（daily）保留省略号 → 兼容 Stage 0.5
    assert render_for_user("……嗯，你好。") == "……嗯，你好。"
