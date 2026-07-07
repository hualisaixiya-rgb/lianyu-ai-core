"""世界状态追踪器 —— Chat Experience V2 核心组件。

Rule First, LLM Second 原则：
- 程序能判断的 → 正则匹配，零 Token
- 程序判断不了的 → 轻量 LLM Fallback（~5% 场景）

包含：
- WorldState: 用户当前世界状态（地点、活动、天气等）
- ActiveTopics: 活跃话题管理（多话题 + 分数衰减）
- ExpressionTracker: 表达多样性追踪
- TimeSystem: 纯程序时间计算
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ================================================================
# Time System（纯程序计算，零 Token）
# ================================================================

def get_time_context() -> str:
    """获取完整时间上下文。纯程序计算，零 Token 消耗。"""
    now = datetime.now()

    hour = now.hour
    if hour < 5:
        period = "凌晨"
    elif hour < 8:
        period = "早晨"
    elif hour < 11:
        period = "上午"
    elif hour < 13:
        period = "中午"
    elif hour < 17:
        period = "下午"
    elif hour < 19:
        period = "傍晚"
    elif hour < 22:
        period = "夜晚"
    else:
        period = "深夜"

    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    weekday = weekdays[now.weekday()]

    month = now.month
    if month in (3, 4, 5):
        season = "春季"
    elif month in (6, 7, 8):
        season = "夏季"
    elif month in (9, 10, 11):
        season = "秋季"
    else:
        season = "冬季"

    return (
        f"{now.year}年{now.month}月{now.day}日 "
        f"星期{weekday} {season} {period} "
        f"{now.hour:02d}:{now.minute:02d}"
    )


# ================================================================
# World State（Rule Engine 维护）
# ================================================================

@dataclass
class WorldState:
    """用户当前所处的世界状态。会话级，不写数据库。"""

    location: str = ""
    activity: str = ""
    weather: str = ""
    temperature_feeling: str = ""
    sky: str = ""
    wind: str = ""
    user_mood: str = ""
    crowd: str = ""

    updated_at: str = ""

    def to_prompt(self) -> str:
        """格式化为 Prompt 注入文本。空字段不显示。"""
        lines: list[str] = []

        field_labels = {
            "location": "地点",
            "activity": "活动",
            "temperature_feeling": "体感",
            "weather": "天气",
            "sky": "天空",
            "wind": "风",
            "crowd": "周围",
        }

        parts = []
        for key, label in field_labels.items():
            value = getattr(self, key, "")
            if value:
                parts.append(f"{label}：{value}")

        if self.user_mood:
            parts.append(f"用户状态：{self.user_mood}")

        if not parts:
            return ""

        lines.append("【当前世界】")
        lines.extend(f"  {p}" for p in parts)
        return "\n".join(lines)

    def is_empty(self) -> bool:
        """是否完全为空。"""
        return not any([
            self.location, self.activity, self.weather,
            self.temperature_feeling, self.sky, self.wind,
            self.user_mood, self.crowd,
        ])


# ================================================================
# Pattern Table（规则表：pattern → field=value）
# ================================================================

# 每条规则: (regex_pattern, field_name, extracted_value_or_match_group)
#   - 如果 value 是整数，表示 regex group index
#   - 如果 value 是字符串，直接使用
#   - pattern 中的 (?P<v>...) 命名组优先

RULES: list[tuple[str, str, Any]] = [
    # ======== 地点（关键词优先） ========
    (r"在(操场|食堂|宿舍|教室|图书馆|便利店|路上|家里|公司|学校|医院|车站|超市|公园|操场)", "location", 1),
    (r"坐在(操场|食堂|宿舍|教室|图书馆|便利店|路上|家里|公司|学校|医院|车站|超市|公园)", "location", 1),
    (r"我在(操场|食堂|宿舍|教室|图书馆|便利店|路上|家里|公司|学校|医院|车站|超市|公园)", "location", 1),
    (r"到(操场|食堂|宿舍|教室|图书馆|便利店|路上|家里|公司|学校|医院|车站|超市|公园)了", "location", 1),
    (r"回(宿舍|家|教室|寝室|房间)", "location", 1),
    # ======== 活动（关键词优先） ========
    (r"在(排练|上课|吃饭|开会|等人|休息|跑步|打球|逛街|看书|写作业|考试|面试|训练)", "activity", 1),
    (r"要去(排练|上课|吃饭|开会|跑步|打球|逛街|面试|训练|彩排)", "activity", 1),
    (r"准备(回宿舍|回家|排练|上课|吃饭|考试|面试)", "activity", 1),
    (r"还在?(排练|上课|吃饭|等人|写作业|开会|训练|统计人数)", "activity", 1),
    (r"开始(排练|上课|吃饭|开会|考试|训练)了?", "activity", 1),
    (r"(?:排练|上课|吃饭|开会|训练|考试|面试|彩排)结束", "activity", 0),
    # 活动（独立动词 Fallback，在"在X"无法覆盖时兜底）
    (r"(排练|上课|吃饭|开会|等人|休息|跑步|打球|逛街|训练|彩排)", "activity", 1),
    # ======== 体感 ========
    (r"好热|很热|太热|热死了|热得|好烫", "temperature_feeling", "炎热"),
    (r"凉快|起风了|风来了|凉了|凉风|凉意", "temperature_feeling", "凉快了"),
    (r"好冷|很冷|太冷|冷死了|冷得", "temperature_feeling", "冷"),
    (r"闷热|闷得|好闷|很闷", "temperature_feeling", "闷热"),
    (r"暖和|温暖|暖洋洋", "temperature_feeling", "温暖"),
    # ======== 天空 ========
    (r"天黑了|天已经黑|天都黑了", "sky", "天黑了"),
    (r"天还亮|天没黑|天还没亮", "sky", "天还亮着"),
    (r"晚霞|夕阳|落日|余晖", "sky", "晚霞"),
    (r"太阳.*(?:没了|下去|落|下山)", "sky", "日落"),
    (r"星星|星光|星空", "sky", "星星出来了"),
    # ======== 风 ========
    (r"起风了|风来了|风吹|有风|风大|风很大|风好大", "wind", "有风"),
    (r"风停了|没风|无风|风小", "wind", "无风"),
    # ======== 情绪 ========
    (r"好累|很累|累死|累[了啦]|疲劳|好困|好倦|好乏", "user_mood", "疲劳"),
    (r"开心|高兴|快乐|好开心|好高兴|好快乐|真开心", "user_mood", "开心"),
    (r"难过|伤心|难受|想哭|好想哭|眼泪|哭[了啦]|哽咽", "user_mood", "难过"),
    (r"好烦|烦躁|烦死|心烦|好躁", "user_mood", "烦躁"),
    (r"紧张|好紧张|紧张死|慌", "user_mood", "紧张"),
    (r"无聊|好无聊|没意思|无趣", "user_mood", "无聊"),
    (r"好饿|很饿|饿死|饿了|好想吃", "user_mood", "饿"),
    # ======== 周围 ========
    (r"好多人|很多人|人多|人好多|人很多|人超多", "crowd", "人很多"),
    (r"没人|一个人都没有|空无一人|没人了", "crowd", "安静"),
    (r"好吵|很吵|吵死|嘈杂|吵闹|喧闹|吵杂", "crowd", "嘈杂"),
]


def _clean_match(text: str) -> str:
    """清洗匹配结果。截断过长内容，去除语气词。"""
    text = text.strip()
    # 限制长度
    if len(text) > 20:
        text = text[:20] + "…"
    # 去除常见语气词后缀
    for suffix in ["了呢", "了吗", "了吧", "了呀", "了啊", "呢", "吗", "吧", "呀", "啊"]:
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[:-len(suffix)]
            break
    return text


def apply_rules(user_message: str) -> dict[str, str]:
    """对单条用户消息执行全部规则匹配。

    每个字段取首次匹配。后续匹配不覆盖（第一印象优先）。

    Args:
        user_message: 用户消息文本

    Returns:
        {field_name: extracted_value}，可能为空 dict
    """
    result: dict[str, str] = {}

    for pattern, field, value in RULES:
        # 每个字段只取首次匹配
        if field in result:
            continue

        m = re.search(pattern, user_message)
        if not m:
            continue

        if isinstance(value, int):
            # group index
            try:
                extracted = _clean_match(m.group(value))
                if extracted:
                    result[field] = extracted
            except IndexError:
                continue
        elif isinstance(value, str):
            result[field] = value

    return result


def update_world_state(
    user_message: str,
    current: WorldState | None,
) -> WorldState:
    """基于用户消息更新 World State。

    Rule Engine 先行。只更新有规则命中的字段。
    未命中的字段保持原值。

    Args:
        user_message: 用户最新消息
        current: 当前 World State（首次为 None）

    Returns:
        更新后的 World State
    """
    if current is None:
        current = WorldState()

    updates = apply_rules(user_message)
    if not updates:
        return current

    # 应用更新
    for field, value in updates.items():
        old_value = getattr(current, field, "")
        if old_value != value:
            setattr(current, field, value)

    current.updated_at = datetime.now().strftime("%H:%M")
    return current


def needs_llm_fallback(
    user_message: str,
    state: WorldState,
    consecutive_no_match: int,
) -> bool:
    """判断是否需要 LLM Fallback 来解析复杂语义。

    触发条件（同时满足）：
    1. 消息包含复杂语义标记（转折/因果/否定/长文本）
    2. activity 为空 OR 明确否定之前状态 OR 连续 3 轮无命中

    Args:
        user_message: 用户消息
        state: 当前 World State
        consecutive_no_match: 连续未命中轮数

    Returns:
        是否需要 LLM Fallback
    """
    # 短消息不触发
    if len(user_message) < 10:
        return False

    has_complex = any(kw in user_message for kw in [
        "但是", "不过", "其实", "结果", "没想到", "突然",
        "因为", "所以", "于是", "导致", "原来",
    ])

    has_negation = any(kw in user_message for kw in [
        "不是", "没有", "并非", "错了",
    ])

    activity_unknown = not state.activity
    many_misses = consecutive_no_match >= 3

    return has_complex and (activity_unknown or has_negation or many_misses)


# ================================================================
# Active Topics（活跃话题管理）
# ================================================================

@dataclass
class Topic:
    """一个活跃话题。"""

    name: str
    score: float = 85.0
    category: str = "其他"
    status: str = "观察中"
    notes: list[str] = field(default_factory=list)
    mention_count: int = 1
    first_seen: str = ""
    last_seen: str = ""

    MAX_NOTES: int = 3


# 话题 → 触发关键词
TOPIC_KEYWORDS: dict[str, tuple[str, list[str]]] = {
    "排练": ("活动", ["排练", "统计人数", "导演", "舞台", "剧本", "台词", "表演", "彩排"]),
    "猫猫云": ("自然", ["猫猫云", "小猫云", "猫云", "像猫的云", "猫形状的云"]),
    "晚霞": ("自然", ["晚霞", "夕阳", "落日", "橘色天边", "天边的颜色"]),
    "吃饭": ("活动", ["吃饭", "食堂", "晚饭", "午饭", "饿了", "吃的", "夜宵", "拉面", "披萨"]),
    "宿舍": ("生活", ["宿舍", "回去", "回寝", "寝室", "房间"]),
    "Sakura": ("人物", ["Sakura", "撒库拉", "路明非"]),
    "天气": ("自然", ["天气", "好热", "好冷", "下雨", "下雪", "闷热", "凉快"]),
    "操场": ("校园", ["操场", "跑道", "草坪", "球场上"]),
}


# 新话题触发模式
NEW_TOPIC_PATTERNS: list[tuple[str, str]] = [
    # (regex, category)
    (r"我要去(.+?)(?:[了啦吧]|$)", "活动"),
    (r"我想(.+?)(?:[了啦吧]|$)", "活动"),
    (r"看到.{0,5}(?:一朵|一只|一个)?(.+?)(?:[，。！…]|$)", "自然"),
    (r"跟你说.{0,3}(.+?)(?:[，。！…]|$)", "其他"),
    (r"发现(.+?)(?:[，。！…]|$)", "生活"),
    (r"(.+?)是谁", "人物"),
    (r"今天(.+?)(?:[，。！…]|$)", "活动"),
]


@dataclass
class ActiveTopics:
    """活跃话题管理器。"""

    topics: list[Topic] = field(default_factory=list)
    history: list[Topic] = field(default_factory=list)

    DECAY_RATE: float = 0.85
    BOOST_NEW: float = 85.0
    BOOST_MENTION: float = 15.0
    MIN_SCORE: float = 10.0
    MAX_SCORE: float = 100.0
    MAX_TOPICS: int = 5
    MAX_NOTES: int = 3

    def update(self, user_message: str) -> None:
        """根据用户消息更新话题分数。

        1. 检查已有话题是否被提及 → +BOOST_MENTION
        2. 未提及的话题 → 衰减
        3. 检查是否有新话题
        4. 淘汰低分话题

        Args:
            user_message: 用户消息
        """
        matched_existing = False
        now = datetime.now().strftime("%H:%M")

        # Phase 1: 已有话题匹配 & 衰减
        for topic in self.topics:
            if self._topic_mentioned(topic, user_message):
                topic.score = min(topic.score + self.BOOST_MENTION, self.MAX_SCORE)
                topic.mention_count += 1
                topic.last_seen = now
                matched_existing = True

                # 提取关键信息（简单规则）
                note = self._extract_note(topic, user_message)
                if note and note not in topic.notes:
                    topic.notes.append(note)
                    if len(topic.notes) > self.MAX_NOTES:
                        topic.notes = topic.notes[-self.MAX_NOTES:]

                # 更新状态
                if self._is_ending(user_message):
                    topic.status = "已结束"
            else:
                topic.score *= self.DECAY_RATE

        # Phase 2: 新话题发现
        if not matched_existing:
            new_topic = self._discover_new_topic(user_message)
            if new_topic is not None:
                self.topics.append(new_topic)

        # Phase 3: 淘汰低分话题
        for topic in list(self.topics):
            if topic.score < self.MIN_SCORE:
                self.topics.remove(topic)
                self.history.append(topic)

        # Phase 4: 按分数排序，限制数量
        self.topics.sort(key=lambda t: t.score, reverse=True)
        if len(self.topics) > self.MAX_TOPICS:
            overflow = self.topics[self.MAX_TOPICS:]
            self.topics = self.topics[:self.MAX_TOPICS]
            self.history.extend(overflow)

    def to_prompt(self) -> str:
        """格式化为 Prompt 注入文本。"""
        if not self.topics:
            return ""

        lines = ["【当前话题】"]
        for i, topic in enumerate(self.topics[:3]):  # 只注入前 3 个
            status_mark = ""
            if topic.status == "进行中":
                status_mark = " 🔄"
            elif topic.status == "已结束":
                status_mark = " ✓"

            notes_str = ""
            if topic.notes:
                notes_str = " — " + "；".join(topic.notes[-2:])

            lines.append(
                f"  {i+1}. {topic.name}（{topic.score:.0f}分）{status_mark}{notes_str}"
            )

        # 如果第一个话题分数显著高于第二个，加引导
        if len(self.topics) >= 2:
            if self.topics[0].score - self.topics[1].score >= 30:
                lines.append(f"  请优先围绕「{self.topics[0].name}」展开对话。")

        return "\n".join(lines)

    def is_empty(self) -> bool:
        return len(self.topics) == 0

    # ---- 内部方法 ----

    @staticmethod
    def _topic_mentioned(topic: Topic, message: str) -> bool:
        """检查消息是否涉及某话题。"""
        # 直接包含话题名
        if topic.name in message:
            return True
        # 关键词匹配
        for name, (cat, keywords) in TOPIC_KEYWORDS.items():
            if name == topic.name:
                for kw in keywords:
                    if kw in message:
                        return True
        return False

    @staticmethod
    def _is_ending(message: str) -> bool:
        """判断消息是否表示话题结束。"""
        return any(kw in message for kw in [
            "散了", "结束了", "完了", "没了", "结束了", "不在了",
        ])

    @staticmethod
    def _extract_note(topic: Topic, message: str) -> str | None:
        """从消息中提取话题相关的关键信息。规则：提取话题名后面的短句。"""
        if topic.name not in message:
            return None
        # 简单截取：话题名后最多 15 字
        idx = message.find(topic.name)
        after = message[idx + len(topic.name):idx + len(topic.name) + 20]
        after = after.strip("，。！…、的了吗呢吧啊")
        if len(after) >= 2:
            return topic.name + after
        return None

    def _discover_new_topic(self, message: str) -> Topic | None:
        """尝试从消息中发现新话题。"""
        # 1. 关键词表匹配
        for name, (category, keywords) in TOPIC_KEYWORDS.items():
            if name in message or any(kw in message for kw in keywords):
                # 检查是否已存在
                if any(t.name == name for t in self.topics):
                    return None
                return Topic(
                    name=name,
                    score=self.BOOST_NEW,
                    category=category,
                    status="观察中",
                    first_seen=datetime.now().strftime("%H:%M"),
                    last_seen=datetime.now().strftime("%H:%M"),
                )

        # 2. 模式匹配
        for pattern, category in NEW_TOPIC_PATTERNS:
            m = re.search(pattern, message)
            if m:
                name = _clean_match(m.group(1))
                if len(name) >= 2 and len(name) <= 15:
                    # 避免与已有话题重复
                    if any(t.name == name for t in self.topics):
                        return None
                    return Topic(
                        name=name,
                        score=self.BOOST_NEW,
                        category=category,
                        status="观察中",
                        first_seen=datetime.now().strftime("%H:%M"),
                        last_seen=datetime.now().strftime("%H:%M"),
                    )

        return None


# ================================================================
# Expression Tracker（表达多样性）
# ================================================================

# 分类意象池
EXPRESSION_POOL: dict[str, dict] = {
    "自然": {
        "items": [
            "云", "风", "晚霞", "星星", "月亮", "雨", "雪",
            "露水", "霜", "彩虹", "晨光", "暮色", "薄雾",
            "蝉鸣", "蛙声", "萤火虫", "蜻蜓",
        ],
        "priority": 0.3,
    },
    "生活": {
        "items": [
            "小猫", "糖果", "玻璃珠", "便利店", "纸飞机",
            "风铃", "铅笔", "汽水瓶", "冰棍", "风扇",
            "蚊香", "凉席", "蒲扇", "闹钟", "台灯",
        ],
        "priority": 0.35,
    },
    "校园": {
        "items": [
            "操场", "食堂", "树荫", "课桌", "黑板", "走廊",
            "图书馆", "篮球场", "跑道", "饮水机", "书包", "课本",
        ],
        "priority": 0.2,
    },
    "角色": {
        "items": [
            "绘本", "小黄鸭", "草莓大福", "巧克力", "玻璃弹珠",
            "白色连衣裙", "日记本", "樱花",
        ],
        "priority": 0.15,
    },
}


@dataclass
class ExpressionTracker:
    """表达多样性追踪器。"""

    recent_categories: list[str] = field(default_factory=list)
    """最近使用的类别，最多保留 3 个"""

    recent_items: list[str] = field(default_factory=list)
    """最近使用的具体意象，最多保留 5 个"""

    def to_prompt_guide(self) -> str:
        """生成表达多样性 Prompt 指令。"""
        lines = [
            "表达指南：",
            "- 每轮最多使用一个具体意象",
            "- 不要连续两轮使用同一类别的意象（自然→生活→校园→角色，交替）",
            "- 多从「生活」和「校园」类别中取材——它们比自然意象更接地气",
            "- 不说话也是一种表达。不是每轮都需要意象",
        ]

        if self.recent_categories:
            cats = " → ".join(self.recent_categories[-3:])
            lines.append(f"- 最近使用的类别：{cats}")
        if self.recent_items:
            items = "、".join(self.recent_items[-5:])
            lines.append(f"- 最近使用的意象：{items}（请避免重复）")

        return "\n".join(lines)

    def record(self, category: str | None = None, item: str | None = None) -> None:
        """记录一次使用。供将来 LLM 自我报告后调用（暂不强制）。"""
        if category:
            self.recent_categories.append(category)
            if len(self.recent_categories) > 3:
                self.recent_categories = self.recent_categories[-3:]
        if item:
            self.recent_items.append(item)
            if len(self.recent_items) > 5:
                self.recent_items = self.recent_items[-5:]
