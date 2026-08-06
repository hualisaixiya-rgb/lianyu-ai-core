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
    DAILY_SPEC,
    DEEP_SPEC,
    EMOTION_SPEC,
    apply_expression,
    collapse_lines,
    dedup_adjacent_sentences,
    infer_spec,
    normalize_ellipsis_prefix,
    truncate_to_max,
)
from utils.response_renderer import render_for_storage, render_for_user

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden_cases" / "expression"
GOLDEN_FILE = GOLDEN_DIR / "cases.json"

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
