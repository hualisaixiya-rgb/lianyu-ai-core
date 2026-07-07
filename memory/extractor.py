"""记忆提取器 —— Memory Safety V1。

从一轮对话中同时提取：
1. Profile 更新 —— 身份信息（姓名、学校等），存储到 user_profiles
2. LongMemory —— 只提取用户明确陈述的事实，存储到 memory_records

一次 LLM 调用完成两类提取，减少 API 开销。
"""

import json
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class ExtractionResult:
    """提取结果。"""

    profile_fields: dict[str, str | list[str] | None] = field(default_factory=dict)
    profile_confidence: dict[str, int] = field(default_factory=dict)
    """每个字段的置信度 {field_name: confidence}"""

    evidence: str = ""
    """用户原话证据"""

    memories: list[dict] = field(default_factory=list)

    @property
    def has_profile_updates(self) -> bool:
        return len(self.profile_fields) > 0

    @property
    def has_memories(self) -> bool:
        return len(self.memories) > 0


# ================================================================
# 提取 System Prompt（Memory Safety — 只提取用户明确陈述）
# ================================================================

EXTRACTION_PROMPT = """# 记忆提取指令

从以下对话中提取关于**用户**的信息。

## 核心规则

只提取用户（User）明确说出的长期事实。
不要从 AI 的回复中提取任何内容。
AI 说的话不是用户的事实。

示例：
  User: "我喜欢下雨天"
  AI: "我也是。雨声很好听。"
  → 提取: "用户喜欢下雨天" ✅
  → 不提取: "雨声很好听" ❌（AI 说的）

  User: "今天好累"
  AI: "辛苦了。像上次一样休息一会儿吧。"
  → 不提取 ❌（"好累"是临时状态；"像上次"是 AI 编的，无证据）

## 提取标准

只提取同时满足：
1. 用户在 User 消息中明确陈述
2. 具有长期价值（不是临时状态/情绪）
3. 可被用户原话证实

不提取：
- 临时状态（"好累""好热""好饿"）
- 纯情绪（"好难过""好开心"）
- AI 说的话
- 推断或猜测

## Profile
身份字段：name/nickname/birthday/school/major/job/likes/dislikes。
姓名必须完整保留原文，一字不差。

## 输出格式

```json
{
  "profile": {"name": null, ...},
  "memories": [
    {"key": "标签", "value": "用户明确说出的事实", "importance": 6}
  ]
}
```

无值得记忆的内容 → 返回空数组。宁缺毋滥。"""


class MemoryExtractor:
    """记忆提取器。"""

    # ---- Profile Intent Detection ----

    @staticmethod
    def _detect_profile_intent(user_message: str) -> str:
        """检测用户关于身份信息的意图（纯规则，零 Token）。

        Returns:
            "NAME_SET" — 普通自称 "我叫a"
            "NAME_CHANGE_CONFIRM" — 明确要求修改 "以后叫我a"
            "NONE" — 不涉及身份修改
        """
        msg = user_message.strip()

        # 明确修改意图
        change_patterns = [
            r"以后叫我", r"把名字改成", r"名字改成", r"改成.*叫我",
            r"对[，,]?\s*把名字", r"对[，,]?\s*叫我",
            r"改个名字", r"换个名字", r"改名",
        ]
        import re
        for pat in change_patterns:
            if re.search(pat, msg):
                return "NAME_CHANGE_CONFIRM"

        # 普通自称
        if any(kw in msg for kw in ["我叫", "我的名字是", "我的名字叫"]):
            return "NAME_SET"

        return "NONE"

    # ---- Confidence Calculation ----

    @staticmethod
    def _compute_confidence(user_message: str, field_name: str) -> int:
        """根据用户消息计算某字段的置信度。

        规则（纯程序，不依赖 LLM）：
        - NAME_CHANGE_CONFIRM（"以后叫我a"）→ 9
        - "对，我叫XXX" / 确认语句 → 9
        - "我叫XXX" / "我的名字是XXX"（NAME_SET）→ 7
        - "你可以叫我XXX" → 6
        - "我是XXX"（普通提及） → 5
        - LLM 推断 / 无明确标记 → 3

        Args:
            user_message: 用户原话
            field_name: 字段名

        Returns:
            置信度 1-10
        """
        import re
        msg = user_message.strip()

        # 最高优先级：检测 Intent
        intent = MemoryExtractor._detect_profile_intent(msg)

        # 明确修改意图 → 最高置信度
        if intent == "NAME_CHANGE_CONFIRM":
            return 9

        # 确认语句
        confirmation_patterns = [
            r"对[，,，\s]*我(?:就)?叫", r"是的?[，,，\s]*我(?:就)?叫",
            r"嗯[，,，\s]*我叫", r"没错[，,，\s]*我叫",
        ]
        for pat in confirmation_patterns:
            if re.search(pat, msg):
                return 9

        # 主动自我介绍
        if any(kw in msg for kw in ["我叫", "我的名字是", "我的名字叫"]):
            return 7

        # 昵称/称呼偏好
        if any(kw in msg for kw in ["你可以叫我", "叫我", "喊我"]):
            return 6

        # 普通提及身份
        if any(kw in msg for kw in ["我是", "我学", "我在", "我做", "我读", "我从事"]):
            return 5

        return 3

    async def extract(
        self,
        user_message: str,
        ai_reply: str,
        provider,
    ) -> ExtractionResult:
        """从一轮对话中提取 Profile 更新和 LongMemory。

        V1 Restore: 增加身份提取守卫。
        - Profile: 只有用户明确说"我叫xxx"时才提取
        - LongMemory: 见 _should_extract_profile()
        """
        # 守卫：检查是否允许提取 Profile
        if not self._can_extract_profile(user_message):
            # 跳过 Profile 提取，但仍可提取 LongMemory（如果 Phase 3 未禁用）
            # V1 Restore: 只返回空 Profile
            return ExtractionResult()

        conversation = f"用户: {user_message}\nAI: {ai_reply}"

        try:
            raw = await provider.chat(
                messages=[{"role": "user", "content": conversation}],
                system_prompt=EXTRACTION_PROMPT,
            )
        except Exception as e:
            logger.warning(f"记忆提取失败（LLM 调用异常）: {e}")
            return ExtractionResult()

        result = self._parse(raw)

        # 二次守卫：即使 LLM 返回了 Profile，也验证来源
        result.profile_fields = self._validate_profile_fields(
            result.profile_fields, user_message
        )

        # 计算每个字段的置信度 + 证据
        if result.has_profile_updates:
            result.evidence = user_message[:500]
            for field_name in result.profile_fields:
                result.profile_confidence[field_name] = self._compute_confidence(
                    user_message, field_name
                )

        return result

    @staticmethod
    def _can_extract_profile(user_message: str) -> bool:
        """检查用户消息是否包含明确的身份声明。

        只允许：
        - "我叫xxx" "我是xxx" "我的名字是xxx"
        - "你可以叫我xxx"
        - "我学xxx" "我的专业是xxx"
        - "我在xxx上学" "我在xxx工作"
        - "我的生日是xxx"
        - "我喜欢xxx"（仅 likes/dislikes）

        禁止：
        - "你还记得我是谁吗" → 不提取
        - "你知道我是谁吗" → 不提取
        - 所有疑问句 → 不提取
        """
        msg = user_message.strip()

        # 禁止疑问句
        if any(kw in msg for kw in ["记得我吗", "知道我吗", "我是谁", "猜猜", "你猜"]):
            return False

        # 必须有明确的身份声明标记
        identity_markers = [
            "我叫", "我是", "我的名字", "你可以叫我", "我学", "我的专业",
            "我在上学", "我在工作", "我在读", "我的生日", "我毕业于",
            "我读", "我做", "我从事",
        ]
        has_marker = any(marker in msg for marker in identity_markers)

        # 喜欢/不喜欢 也算轻度身份信息
        has_preference = any(kw in msg for kw in ["我喜欢", "我不喜欢", "我讨厌"])

        return has_marker or has_preference

    @staticmethod
    def _validate_profile_fields(
        fields: dict, user_message: str
    ) -> dict:
        """验证提取的 Profile 字段确实来自用户消息。

        简单规则：提取的值必须能在用户消息中找到子串匹配。
        防止 LLM 从 AI 回复中推断身份。
        """
        valid: dict = {}
        for field, value in fields.items():
            if not value or not isinstance(value, str):
                continue
            # 值必须在用户消息中出现（或用户消息的合理变体）
            if value in user_message or any(
                word in user_message for word in value if len(word) >= 2
            ):
                valid[field] = value
        return valid

    @staticmethod
    def _parse(raw: str) -> ExtractionResult:
        """解析 LLM 返回的 JSON。"""
        text = raw.strip()

        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end]
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end]

        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.debug(f"提取结果无法解析为 JSON: {text[:120]}...")
            return ExtractionResult()

        if not isinstance(data, dict):
            return ExtractionResult()

        result = ExtractionResult()

        # Profile
        profile = data.get("profile")
        if isinstance(profile, dict):
            for field in ["name", "nickname", "birthday", "school", "major", "job"]:
                value = profile.get(field)
                if value and isinstance(value, str) and value.strip():
                    result.profile_fields[field] = value.strip()
            for list_field in ["likes", "dislikes"]:
                value = profile.get(list_field)
                if isinstance(value, list) and len(value) > 0:
                    items = [v for v in value if isinstance(v, str) and v.strip()]
                    if items:
                        result.profile_fields[list_field] = items

        # LongMemory
        memories = data.get("memories")
        if isinstance(memories, list):
            for mem in memories:
                if (
                    isinstance(mem, dict)
                    and "key" in mem and "value" in mem
                    and mem["key"].strip() and mem["value"].strip()
                ):
                    importance = mem.get("importance", 5)
                    if isinstance(importance, (int, float)):
                        importance = min(max(int(importance), 1), 10)
                    else:
                        importance = 5
                    result.memories.append({
                        "key": mem["key"].strip(),
                        "value": mem["value"].strip(),
                        "importance": importance,
                    })

        return result
