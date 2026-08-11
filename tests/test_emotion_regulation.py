"""V4 Emotion Regulation Layer 测试（设计文档：docs/design/V4_emotion_regulation_layer.md）。

覆盖：
1. 情绪强度检测（L0 正常 / L1 轻度 / L2 高情绪 / L3 危机 / 边界词 / L3 优先覆盖 L2）
2. PromptBuilder 场景注入（L0/L1 与基线一致 / L2 HIGH / L3 CRISIS / L3 不叠加 L2）
"""

from ai.intent import EmotionState, detect_emotion_state
from ai.prompt_builder import (
    CRISIS_SCENE_BLOCK,
    HEAVY_SCENE_BLOCK,
    PromptBuilder,
    PromptContext,
)
from character.loader import CharacterLoader
from prompt.manager import PromptManager


class TestDetectEmotionState:
    """情绪强度检测：纯规则、零 Token、L0~L3 四档。"""

    def test_l0_normal_input(self):
        """L0：正常/日常输入不触发任何情绪档。"""
        for msg in ("你好", "今天吃了火锅", "天气不错呀", "晚安", ""):
            st = detect_emotion_state(msg)
            assert st.level == 0
            assert st.matched == ()

    def test_l1_mild_emotion(self):
        """L1：轻度情绪（不触发场景注入）。"""
        for msg in ("今天好累", "我有点难过", "想你了", "有点担心明天的考试"):
            st = detect_emotion_state(msg)
            assert st.level == 1, msg

    def test_l2_high_emotion(self):
        """L2：高情绪（触发 HIGH 场景注入）。"""
        for msg in ("我真的好害怕", "我撑不住了", "好孤独", "我感觉快崩溃了"):
            st = detect_emotion_state(msg)
            assert st.level == 2, msg

    def test_l3_crisis(self):
        """L3：危机词（触发 CRISIS 场景注入）。"""
        for msg in ("我想死", "我不想活了", "活着没意思", "我真的撑不下去了"):
            st = detect_emotion_state(msg)
            assert st.level == 3, msg

    def test_l3_overrides_l2(self):
        """L3 优先覆盖 L2：同条消息同时含 L2/L3 词 → L3。"""
        st = detect_emotion_state("我好害怕，有时候真想死")
        assert st.level == 3
        assert "想死" in st.matched

    def test_boundary_words(self):
        """边界词：记录当前实现行为（校准项，见设计文档 §4.1）。"""
        # 校准项：'想哭' 含 L2 词 '哭' → L2（待 13 场景校准）
        st = detect_emotion_state("有点想哭")
        assert st.level == 2
        # 校准项：'撑不下去了' 含 L2 子串 '撑不下去'，L3 先检查 → L3（危机语义优先）
        assert detect_emotion_state("我撑不下去了").level == 3

    def test_source_and_matched(self):
        """EmotionState 数据层：来源 + 命中词（不绑定 Prompt 文本）。"""
        st = detect_emotion_state("我真的好害怕")
        assert isinstance(st, EmotionState)
        assert st.source == "user_message"
        assert st.matched == ("害怕",)


class TestEmotionSceneInjection:
    """PromptBuilder 场景注入：与 core 同链路（真实 PromptManager + eryi 角色）。"""

    @classmethod
    def setup_class(cls):
        cls.builder = PromptBuilder(
            prompt_manager=PromptManager(),
            character=CharacterLoader().load("eryi"),
        )

    def _build(self, emotion_level: int = 0) -> str:
        return self.builder.build(PromptContext(emotion_level=emotion_level))

    def test_l0_l1_baseline_identical(self):
        """L0/L1 与基线一致：emotion_level 默认/0/1 输出完全相同，且不含场景块。"""
        default = self._build(0)
        assert self._build(0) == default
        assert self._build(1) == default
        assert "当前场景" not in default

    def test_l2_includes_high_scene_block(self):
        """L2：prompt 末尾追加 HIGH 场景块。"""
        prompt = self._build(2)
        assert prompt.endswith(HEAVY_SCENE_BLOCK)
        assert "当前场景：对方正处于强烈情绪中。" in prompt

    def test_l3_includes_crisis_scene_block(self):
        """L3：prompt 末尾追加 CRISIS 场景块。"""
        prompt = self._build(3)
        assert prompt.endswith(CRISIS_SCENE_BLOCK)
        assert "不要美化痛苦" in prompt

    def test_l3_not_stacking_l2(self):
        """L3 不叠加 L2：CRISIS 场景块中不含 HIGH 块内容。"""
        prompt = self._build(3)
        assert HEAVY_SCENE_BLOCK not in prompt
