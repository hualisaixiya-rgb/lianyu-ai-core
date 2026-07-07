# Chat Experience V2 —— 设计方案

> 原则：Rule First, LLM Second  
> 日期：2026-07-07  
> 状态：设计阶段，待确认

---

## 一、核心原则

```
┌──────────────────────────────────────────────────┐
│               Rule First, LLM Second              │
│                                                  │
│  程序能判断的 → 程序判断                           │
│  程序判断不了的 → 再交给 LLM                       │
│                                                  │
│  目标：更真实 / 更稳定 / 更少 Token / 更低延迟      │
└──────────────────────────────────────────────────┘
```

### 职责划分

| 层 | 维护者 | 存储 | 生命周期 |
|----|--------|------|---------|
| **Profile** | LLM Extractor | SQLite | 永久 |
| **Relationship** | 程序自动 | SQLite | 永久 |
| **LongMemory** | LLM Extractor | SQLite | 永久 |
| **RecentContext** | 程序自动 | 内存 | 当前会话 |
| **World State** ⭐ | **Rule Engine**（为主） | 内存 | 当前会话 |
| **Active Topics** ⭐ | **Rule Engine** | 内存 | 当前会话 |

---

## 二、World State（世界状态）

### 2.1 数据结构

```python
@dataclass
class WorldState:
    """用户当前所处的世界状态。Rule Engine 维护，不写数据库。"""

    location: str = ""             # 地点：操场 / 食堂 / 宿舍 / 教室 / ...
    activity: str = ""             # 活动：排练 / 吃饭 / 上课 / 回宿舍 / ...
    weather: str = ""              # 天气：炎热 / 凉爽 / 下雨 / ...
    temperature_feeling: str = ""  # 体感：很热 / 凉快了 / 冷 / ...
    sky: str = ""                  # 天空：天还亮着 / 晚霞 / 天黑了 / 星星出来了
    wind: str = ""                 # 风：无风 / 起风了 / 风很大
    user_mood: str = ""            # 情绪：开心 / 累 / 疲劳 / 平静 / 焦急 / ...
    crowd: str = ""                # 周围：人很多 / 安静 / 嘈杂 / ...

    # 元数据
    updated_at: str = ""           # 最后更新时间
    confidence: dict[str, float]   # 每个字段的置信度（Rule=1.0, LLM=<1.0）

    def to_prompt(self) -> str:
        """格式化为 Prompt 注入文本。空字段不显示。"""

    def is_empty(self) -> bool:
        """是否完全为空（首次对话）。"""
```

### 2.2 Rule Engine 规则表

每条规则：`pattern → field=value`。按优先级从高到低匹配。

#### 地点（location）

| 优先级 | Pattern（正则） | 提取值 | 示例 |
|--------|---------------|--------|------|
| 1 | `我在(.+?)(?:[，。！]|$)` | group(1) | "我在操场" → 操场 |
| 2 | `到(.+?)了` | group(1) | "到食堂了" → 食堂 |
| 3 | `回(.+?)(?:[，。！]|$)` | group(1) | "回宿舍" → 宿舍 |
| 4 | `坐在(.+?)(?:[，。！]|$)` | group(1) | "坐在操场上" → 操场 |
| 5 | `去(.+?)(?:[，。！]|$)` | group(1) | "去便利店" → 便利店 |

#### 活动（activity）

| 优先级 | Pattern | 提取值 | 示例 |
|--------|---------|--------|------|
| 1 | `在(.+?)(?:[，。！]|$)` | group(1) | "在排练" → 排练 |
| 2 | `要去(.+?)(?:[，。！]|$)` | group(1) | "要去排练了" → 排练 |
| 3 | `准备(.+?)(?:[，。！]|$)` | group(1) | "准备回宿舍" → 回宿舍 |
| 4 | `还在(.+?)(?:[，。！]|$)` | group(1) | "还在统计人数" → 统计人数 |
| 5 | `开始(.+?)(?:[，。！]|$)` | group(1) | "开始排练了" → 排练 |
| 6 | `(.+?)结束` | group(1)+"结束" | "排练结束" → 排练结束 |

#### 体感（temperature_feeling）

| Pattern | 值 |
|---------|-----|
| `好热\|很热\|太热\|热死了\|热得` | 炎热 |
| `凉快\|起风了\|风来了\|凉了` | 凉快了 |
| `好冷\|很冷\|太冷\|冷死了` | 冷 |
| `闷\|闷热` | 闷热 |
| `暖和\|温暖` | 温暖 |

#### 天空（sky）

| Pattern | 值 |
|---------|-----|
| `天黑了\|天已经黑\|天都黑了` | 天黑了 |
| `天还亮\|天没黑\|天还没黑` | 天还亮着 |
| `晚霞\|夕阳\|落日` | 晚霞 |
| `太阳.*(?:没了\|下去\|落)` | 日落 |
| `星星\|星光` | 星星出来了 |
| `天亮\|早晨\|早上` | 天亮了 |

#### 风（wind）

| Pattern | 值 |
|---------|-----|
| `起风了\|风来了\|风吹\|有风\|风大` | 有风 |
| `风停\|没风\|无风` | 无风 |

#### 情绪（user_mood）

| Pattern | 值 |
|---------|-----|
| `好累\|很累\|累死\|累了\|疲劳\|好困` | 疲劳 |
| `开心\|高兴\|快乐\|好开心` | 开心 |
| `难过\|伤心\|难受\|想哭\|哭` | 难过 |
| `好烦\|烦躁\|烦死了` | 烦躁 |
| `紧张\|好紧张` | 紧张 |
| `无聊\|好无聊` | 无聊 |

#### 周围（crowd）

| Pattern | 值 |
|---------|-----|
| `好多人\|很多人\|人多` | 人很多 |
| `没人\|一个人都没有\|安静` | 安静 |
| `好吵\|很吵\|吵死了\|嘈杂` | 嘈杂 |

### 2.3 更新流程

```
用户消息: "还在统计人数，都等好久了，我现在坐在操场上好热"
                │
                ▼
┌──────────────────────────────────────────┐
│         Rule Engine: update_world_state() │
│                                           │
│  匹配规则（按优先级）:                      │
│                                           │
│  "坐在操场上" → location = "操场"          │
│  "在统计人数" → activity = "统计人数"       │
│  "好热"       → temperature = "炎热"       │
│  "好久了"     → (无匹配规则)                │
│                                           │
│  结果:                                     │
│  location: "操场"        (confidence=1.0)  │
│  activity: "统计人数"     (confidence=1.0)  │
│  temperature: "炎热"     (confidence=1.0)  │
│                                           │
│  ✅ 全部 Rule 命中，不调 LLM                 │
│  Token 消耗: 0                              │
└──────────────────────────────────────────┘
```

### 2.4 LLM Fallback 触发条件

**只有同时满足以下条件才调用 LLM：**

1. 用户消息包含**复杂语义**（检测到以下关键词但规则无法解析）：
   - 转折词："但是/不过/其实/结果/没想到/突然"
   - 因果词："因为/所以/于是/导致"
   - 复杂事件描述（超过 30 字且无规则命中）

2. **且**以下任一条件：
   - activity 字段仍为空
   - 用户明确说"不是X"（否定之前的 state）
   - 连续 3 轮无任何 Rule 命中（用户可能在讲一个复杂故事）

**LLM Fallback 的 Prompt（极简）：**

```
从这句话提取状态，只返回JSON，不解释：
"{user_message}"

当前状态：{current_state_json}

规则：只提取明确说出的。不推断。
{"location":"...","activity":"...","temperature_feeling":"...","sky":"...","wind":"...","user_mood":"...","crowd":"..."}
```

**不触发 LLM Fallback 的场景：**
- "嗯" "好" "知道了" "哈哈哈" → 无状态变化，跳过
- "然后呢" "后来呢" → 追问，不更新 state
- 纯情绪表达但无新事实 → Rule 已覆盖

---

## 三、Active Topics（活跃话题）

### 3.1 数据结构

```python
@dataclass
class Topic:
    """一个活跃话题。"""

    name: str                    # 话题名："排练" / "猫猫云" / "晚霞"
    score: float                 # 当前分数 0-100
    category: str                # 分类：活动 / 自然 / 人物 / 生活 / 其他
    status: str                  # 状态：进行中 / 已结束 / 观察中
    first_seen: str              # 首次出现时间（轮数或时间戳）
    last_seen: str               # 最后提及时间
    notes: list[str]             # 关键信息（最多 3 条）
    mention_count: int           # 被提及次数

@dataclass  
class ActiveTopics:
    """话题管理器。"""

    topics: list[Topic]          # 按 score 降序
    max_topics: int = 5          # 最多保留 5 个话题

    # 参数
    DECAY_RATE: float = 0.85     # 每轮未提及：score *= 0.85
    BOOST_NEW: float = 85.0      # 新话题初始分
    BOOST_MENTION: float = 15.0  # 被提及时加分
    BOOST_USER_ASK: float = 10.0 # 用户主动追问时加分
    MIN_SCORE: float = 10.0      # 低于此分 → 移入历史
    MAX_SCORE: float = 100.0     # 分数上限

    # 历史话题（已降权移除的）
    history: list[Topic]
```

### 3.2 话题生命周期

```
用户说: "我要去排练了"
  → 新增 Topic("排练", score=85, category="活动", status="进行中")

用户说: "这里好多人"
  → "排练" 被提及 → score = min(85+15, 100) = 100

用户说: "我看到一朵猫猫云"
  → 新增 Topic("猫猫云", score=85, category="自然", status="观察中")
  → "排练" 未提及 → score = 100*0.85 = 85

用户说: "小猫云散了"
  → "猫猫云" 被提及 → score = min(85+15, 100) = 100
  → status 更新为 "已结束"
  → "排练" 未提及 → score = 85*0.85 = 72

用户说: "还在统计人数，好热"
  → "排练" 被提及（"统计人数"匹配排练关键词）
  → score = min(72+15, 100) = 87
  → "猫猫云" 未提及 → score = 100*0.85 = 85

...(10 轮后，一直在聊排练)...

  → "排练" score = 100
  → "猫猫云" score = 85 * 0.85^10 = 16 → 接近淘汰

...(20 轮后)...

  → "猫猫云" score = 16 * 0.85^10 = 3.2 → < 10 → 移入 history
```

### 3.3 话题关键词映射

Rule Engine 通过关键词判断"用户当前在说哪个话题"：

```python
# 话题 → 触发关键词（不区分大小写）
TOPIC_KEYWORDS = {
    "排练": ["排练", "统计人数", "导演", "舞台", "剧本", "台词", "表演"],
    "猫猫云": ["猫猫云", "小猫云", "猫云", "像猫的云"],
    "晚霞": ["晚霞", "夕阳", "落日", "橘色", "天边"],
    "吃饭": ["吃饭", "食堂", "晚饭", "午饭", "饿了", "吃的"],
    "宿舍": ["宿舍", "回去", "回寝", "寝室"],
    "Sakura": ["Sakura", "撒库拉", "路明非"],
}
```

### 3.4 新话题发现

当用户消息包含以下模式但无法匹配已有话题时，创建新话题：

| 触发模式 | 示例 | category |
|----------|------|----------|
| `我要去/我要/我想` + 动词 | "我要去排练了" | 活动 |
| `看到/发现/注意到` + 名词 | "我看到一朵猫猫云" | 自然/生活 |
| `跟你说/告诉你` + 事件 | "我跟你说，这里好多人" | 活动 |
| 出现新的人名 | "Sakura是谁" | 人物 |

---

## 四、Expression Pool（表达池）

### 4.1 分类意象池

```python
EXPRESSION_POOL = {
    "自然": {
        "items": ["云", "风", "晚霞", "星星", "月亮", "雨", "雪", "露水",
                  "霜", "彩虹", "晨光", "暮色", "薄雾", "蝉鸣", "蛙声"],
        "priority": 0.3,   # 使用权重
    },
    "生活": {
        "items": ["小猫", "糖果", "玻璃珠", "便利店", "纸飞机", "萤火虫",
                  "风铃", "铅笔", "橡皮", "汽水瓶", "冰棍", "风扇",
                  "蚊香", "凉席", "蒲扇"],
        "priority": 0.35,
    },
    "校园": {
        "items": ["操场", "食堂", "树荫", "课桌", "黑板", "走廊", "图书馆",
                  "篮球场", "跑道", "饮水机", "书包", "课本"],
        "priority": 0.2,
    },
    "角色": {
        "items": ["绘本", "小黄鸭", "草莓大福", "巧克力", "玻璃弹珠",
                  "白色连衣裙", "日记本"],
        "priority": 0.15,
    },
}
```

### 4.2 使用规则

```python
class ExpressionTracker:
    """跟踪最近使用的表达类别和具体意象。"""

    recent_categories: list[str]     # 最近 3 轮的类别
    recent_items: list[str]          # 最近 5 轮的具体意象

    def should_use(self, category: str, item: str) -> bool:
        """判断是否应该使用此意象。"""
        # 1. 同一类别不在最近 2 轮内连续使用
        if category in self.recent_categories[-2:]:
            return False
        # 2. 同一意象不在最近 5 轮内重复
        if item in self.recent_items:
            return False
        return True

    def suggest_category(self) -> str:
        """建议本次使用的类别（加权随机，避开最近使用的）。"""
```

**System Prompt 指令**：

```
表达指南：
- 每轮最多使用一个具体意象
- 不要连续两轮使用同一类别（自然→生活→校园→角色，交替）
- 多从"生活"和"校园"类别中取材——它们比"自然"更接地气
- 不说话也是一种表达。不是每轮都需要意象
```

---

## 五、时间系统

### 5.1 纯程序计算

```python
from datetime import datetime

def get_time_context() -> str:
    """纯程序计算，零 Token 消耗。"""
    now = datetime.now()

    # 时间段
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

    # 星期
    weekdays = ["一", "二", "三", "四", "五", "六", "日"]
    weekday = weekdays[now.weekday()]

    # 季节（气象划分）
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
        f"星期{weekday} {season} {period} {now.hour:02d}:{now.minute:02d}"
    )
```

输出示例：`2026年7月7日 星期二 夏季 傍晚 18:30`

### 5.2 System Prompt 时间指令

```
[9] 关于时间：
系统提供了真实时间。不要自行猜测天是否黑了、路灯是否亮了。
如果用户描述了实际场景（"天还亮着呢"），以用户描述为准，
更新到【当前世界】后使用。
```

---

## 六、System Prompt 最终结构

```
[1] 你是绘梨衣...(不变)
[2] 对话是日常状态...(不变)
[3] 先回应心情...(修改：加主动了解)
[4] 回复简短...(不变)
[5] 情绪是缓慢的河...(不变)
[6] 连续性规则...(不变)

[7] 主动陪伴：
当【当前话题】中有一个进行中的活动时，优先围绕它展开对话。
- 关心进展："开始了吗？""还在等吗？"
- 关心感受："站了很久腿酸吗？""导演严格吗？"
- 不要每轮都切到新的自然意象。事件是第一话题。
当用户说累/热/困时，先了解原因再陪伴。不跳过了解直接安慰。

[8] 表达多样性：
（意象池使用指南 + 类别交替规则）

[9] 时间真实：
使用系统提供的时间。不猜测。不编造。

【当前世界】（Rule Engine 维护，零 LLM 成本）
地点：操场
活动：排练等待中
体感：炎热
天空：傍晚，天还亮着
周围：人很多
用户状态：疲劳

【当前话题】（Rule Engine 维护，零 LLM 成本）
1. 排练（95分）— 进行中，下午开始，在操场
2. 猫猫云（42分）— 已结束，刚才散了
3. 晚霞（25分）— 快结束了

{conversation_summary}

{identity}

{profile_context}

{world_context}

{memory_context}

真实时间：2026年7月7日 星期二 夏季 傍晚 18:30
```

---

## 七、数据流

```
Telegram Message: "还在统计人数，好热，我坐在操场上"
        │
        ▼
┌─────────────────────────────────────────────────┐
│  PHASE 1: Rule Engine（程序，零 Token）          │
│                                                 │
│  1a. 更新 World State                            │
│      - location = "操场"       (matched: "坐在操场上")│
│      - activity = "统计人数"     (matched: "在统计人数")│
│      - temperature = "炎热"     (matched: "好热")    │
│      - user_mood = "疲劳"       (matched: "好累")    │
│      - confidence: all 1.0                       │
│      ✅ 无需 LLM Fallback                        │
│                                                 │
│  1b. 更新 Active Topics                          │
│      - "排练": 已存在 → +15 (mention) → score=95 │
│      - "猫猫云": 未提及 → *0.85 → score=35       │
│      - 无新话题触发                               │
│                                                 │
│  1c. 更新 Expression Tracker                     │
│      - 记录本轮未使用意象（由 LLM 自由选择）       │
│                                                 │
│  Token 消耗: 0                                   │
│  耗时: <1ms                                      │
└─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────┐
│  PHASE 2: Memory Retrieval（已有，不改）          │
│                                                 │
│  - Profile 常驻加载                               │
│  - LongMemory 按需搜索                            │
│  - Relationship 静默注入                          │
│                                                 │
│  Token 消耗: 0（数据读取）                         │
└─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────┐
│  PHASE 3: Build System Prompt                   │
│                                                 │
│  - 注入 World State (from Phase 1a)              │
│  - 注入 Active Topics (from Phase 1b)            │
│  - 注入 Profile + Memory (from Phase 2)          │
│  - 注入真实时间 (纯程序)                           │
│  - 注入规则 [1]-[9]                              │
│                                                 │
│  Token 消耗: ~300 tokens（新增部分）               │
│  （相比旧版增加 ~200 tokens，但消除了一轮 LLM 调用）│
└─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────┐
│  PHASE 4: LLM Generate Reply                    │
│                                                 │
│  - 正常调用，无额外开销                            │
└─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────┐
│  PHASE 5: Memory Extract（异步，不改）            │
└─────────────────────────────────────────────────┘
```

---

## 八、LLM Fallback 触发统计（预估）

基于测试记录中的 50+ 轮对话：

| 用户消息 | Rule 命中？ | 触发 LLM Fallback？ |
|----------|-----------|-------------------|
| "我要去排练了" | 活动=排练 | ❌ 不触发 |
| "你不和我一起去吗" | 无状态变化 | ❌ 不触发 |
| "现在好热" | 体感=炎热 | ❌ 不触发 |
| "起风了" | 风=有风 | ❌ 不触发 |
| "我在操场排练" | 地点=操场，活动=排练 | ❌ 不触发 |
| "我正想问你在干嘛呢" | 无状态变化 | ❌ 不触发 |
| "我看到一朵猫猫云" | 新话题 | ❌ Rule 发现新话题 |
| "小猫云散了" | 天空更新 | ❌ 不触发 |
| "天慢慢黑了呢" | 天空=天黑了 | ❌ 不触发 |
| "Sakura是谁呀？" | 新话题(人物) | ❌ Rule 创建话题 |
| "他对于你来说应该是很重要的人吧" | 无状态变化 | ❌ 不触发 |
| "你是路明非吧" | 复杂语义 | ⚠️ 可能触发（如 Rule 无法判断）|
| **预计 Fallback 率** | | **<5%** |

---

## 九、涉及文件

### 新建

| 文件 | 说明 |
|------|------|
| `ai/world_tracker.py` | WorldState + ActiveTopics + RuleEngine + ExpressionTracker + TimeSystem |

### 修改

| 文件 | 改动 | 说明 |
|------|------|------|
| `ai/core.py` | `ConversationSession` 加 `world_state: WorldState` + `active_topics: ActiveTopics` | 会话级状态 |
| `ai/core.py` | `chat()` 流程：Phase 1(Rule Engine) → Phase 2(Memory) → Phase 3(Prompt) → Phase 4(LLM) | 重排流程 |
| `ai/core.py` | `_build_system_prompt()` 加 `world_state_context` + `active_topics_context` + `time_context` 参数 | 新增注入 |
| `prompt/templates/system.yaml` | 加 [7][8][9] 规则 + `{world_state_context}` + `{active_topics_context}` + `{time_context}` | 调整结构 |
| `utils/world_state.py` | 新增 `get_time_context()` 替换 `get_world_context()` | 时间系统升级 |

### 不改

| 目录/文件 | 原因 |
|-----------|------|
| `memory/` 全部 | Memory 四层架构不动 |
| `adapters/` 全部 | Telegram 适配器不改 |
| `voice/` 全部 | 语音模块无关 |
| `database/` 全部 | 不新增表 |
| `character/` 全部 | 角色设定不动 |
| `config/` 全部 | 不需要新配置项 |

---

## 十、为什么这样设计比 V1 更合理

### 10.1 成本对比

| | V1（每轮 LLM 提取） | V2（Rule First） |
|---|---|---|
| World State 更新 | 1 次 LLM 调用 (~150 tokens) | 0（Rule 命中时） |
| 延迟 | +500ms | +0ms |
| 月度额外 Token（按 100 轮/天） | ~450,000 tokens | ~22,500 tokens（仅 5% Fallback） |
| 可靠性 | 依赖 LLM 输出格式 | 确定性规则，100% 可靠 |

### 10.2 可维护性

```
V1: 想加一个"天气"字段 → 修改 LLM extraction prompt → 测试 JSON 解析 → 担心 LLM 不稳定
V2: 想加一个"天气"字段 → 加一条 regex → 加一个字段 → 完成
```

### 10.3 职责清晰

```
Rule Engine → 什么是什么（事实提取）
Memory     → 以前发生过什么（长期记忆）
Topics     → 现在在聊什么（对话方向）
LLM        → 怎么回应（语言生成）
```

每一层职责单一，互不干扰。

### 10.4 跨会话正确性

```
会话 A: World State = {location: "操场", activity: "排练"}
会话结束 → World State 释放

会话 B: World State = {}（全新）
         conversation_summary 中有 "昨天下午用户在操场排练"
         → LLM 通过摘要知道昨天的事
         → 但不混淆为当前状态
```

World State 只在当前会话有效，不会"昨天的操场"污染"今天的教室"。
