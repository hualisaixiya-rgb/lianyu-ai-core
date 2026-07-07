"""Chat Experience 回归测试。

每次修改 System Prompt 或 Memory 后必须运行。
测试关注：不编造、不污染、正确使用记忆。
"""

from ai.core import detect_intent, Intent


# ================================================================
# Test 1: Intent Detection
# ================================================================

def test_intent_greeting():
    """问候 → GREETING。"""
    assert detect_intent("你好呀") == Intent.GREETING
    assert detect_intent("嗨") == Intent.GREETING
    assert detect_intent("在吗") == Intent.GREETING


def test_intent_identity():
    """身份确认 → IDENTITY_CHECK。"""
    assert detect_intent("你还记得我吗") == Intent.IDENTITY_CHECK
    assert detect_intent("我是谁") == Intent.IDENTITY_CHECK
    assert detect_intent("你还记得我不") == Intent.IDENTITY_CHECK


def test_intent_recall():
    """回忆过去 → RECALL_PAST。"""
    assert detect_intent("我们昨天聊了什么") == Intent.RECALL_PAST
    assert detect_intent("之前说过的那个") == Intent.RECALL_PAST


def test_intent_daily():
    """日常聊天 → DAILY_CHAT。"""
    assert detect_intent("今天天气不错") == Intent.DAILY_CHAT
    assert detect_intent("我吃了饭") == Intent.DAILY_CHAT


# ================================================================
# Test 2: Extraction Filter
# ================================================================

def test_should_extract_skip_greeting():
    """寒暄 → 不提取。"""
    from ai.core import AICore
    core = AICore()
    assert not core._should_extract("你好呀", "你好呀。")
    assert not core._should_extract("嗯", "嗯。")


def test_should_extract_skip_mood():
    """临时情绪 → 不提取。"""
    from ai.core import AICore
    core = AICore()
    assert not core._should_extract("今天好累呀", "累了就休息吧。")


def test_should_extract_allow_fact():
    """明确事实 → 可以提取。"""
    from ai.core import AICore
    core = AICore()
    assert core._should_extract(
        "我叫夏离萤，学微电子的",
        "你好呀，夏离萤。微电子很有意思。"
    )


# ================================================================
# Test 3: Prompt Template（不含禁止列表、含关键正向规则）
# ================================================================

def test_prompt_no_negative_lists():
    """Prompt 不应包含大量否定列表。"""
    from prompt.manager import PromptManager
    pm = PromptManager()
    r = pm.render("system",
        identity="", current_time="now", world_context="",
        profile_context="", memory_context="", conversation_summary="",
        relationship_tone="", timeline_context="",
        world_state_context="", active_topics_context="",
    )
    # 正向关键词
    assert "安静" in r
    assert "优先回应当前" in r
    # 不应该有大段 ❌ 列表
    assert r.count("❌") <= 2, f"Too many ❌: {r.count('❌')}"


def test_prompt_has_memory_safety():
    """Prompt 应有记忆安全相关的正向规则。"""
    from prompt.manager import PromptManager
    pm = PromptManager()
    r = pm.render("system",
        identity="", current_time="now", world_context="",
        profile_context="", memory_context="", conversation_summary="",
        relationship_tone="", timeline_context="",
        world_state_context="", active_topics_context="",
    )
    assert "没有记录的事" in r
    assert "不假装记得" in r


# ================================================================
# Test 4: Memory Safety（source 字段）
# ================================================================

def test_memory_record_has_source():
    """MemoryRecord 应有 source 和 evidence 字段。"""
    from database.models.memory import MemoryRecord
    assert hasattr(MemoryRecord, "source")
    assert hasattr(MemoryRecord, "evidence")


# ================================================================
# Test 5: Profile 分级注入
# ================================================================

def test_profile_levels():
    """Profile 三种注入级别。"""
    from memory.stores.profile_store import ProfileStore, ProfileData
    store = ProfileStore()
    pd = ProfileData(name="Xia", nickname="Xiao", major="EE")

    full = store.format_full(pd)
    assert "Xia" in full and "Xiao" in full and "EE" in full

    compact = store.format_compact(pd)
    assert "Xia" in compact and "EE" in compact
    assert "Xiao" not in compact  # Compact: name + 1 field

    minimal = store.format_minimal(pd)
    assert minimal == "对方叫Xia。"

    empty = store.format_minimal(ProfileData())
    assert empty == ""
