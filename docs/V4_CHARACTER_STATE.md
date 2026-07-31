# V4 Character State 详细设计

> Phase 1 | 版本：V4.0 Draft | 日期：2026-07-30

---

## 一、CharacterState 定义

```python
@dataclass
class CharacterState:
    """角色内部状态。每个 (platform, platform_user_id) 一条记录。"""

    platform: str
    platform_user_id: str

    mood: str = "calm"          # 当前情绪
    energy: float = 1.0         # 精力 0.0~1.0
    sleeping: bool = False      # 是否在睡觉

    mood_updated_at: datetime | None = None
    energy_updated_at: datetime | None = None
    updated_at: datetime | None = None
```

### 字段说明

| 字段 | 类型 | 范围 | 说明 |
|------|------|------|------|
| mood | str | calm / happy / sad / concerned / tired / curious | 当前情绪。由事件驱动改变。 |
| energy | float | 0.0 ~ 1.0 | 精力。随时间自然衰减。影响回复长度和主动性。 |
| sleeping | bool | true / false | 是否在睡觉。睡觉时 energy 恢复。 |

### mood 的可能值

| mood | 触发条件 | 表现 |
|------|---------|------|
| calm | 默认状态 | 正常回复 |
| happy | 用户表达开心/感谢 | 回复稍活泼，可能多一句 |
| sad | 用户表达悲伤/离别 | 回复更轻，更多省略号 |
| concerned | 用户表达疲惫/生病/压力 | 回复更关心，多问一句 |
| tired | energy < 0.2 | 回复更短，更慢 |
| curious | 用户提出新话题 | 回复多一个追问 |

### energy 衰减规则

```
正常回复：energy -= 0.05
深度对话（用户消息 > 25 字）：energy -= 0.10
情绪波动（mood 变化）：energy -= 0.03
每小时自然衰减：energy -= 0.02

sleeping=true 时：energy += 0.15/小时
energy 下限：0.0（不会到负数）
energy 上限：1.0
```

### sleeping 规则

```
触发条件（满足任一）：
  - 用户长时间（> 6 小时）未发消息
  - energy < 0.1 且当前为深夜（23:00-06:00）

退出条件：
  - 用户发消息
  - energy 恢复到 0.6 以上
```

---

## 二、State → Prompt 注入

### 注入位置

在 `ai/core.py` 的 `_build_system_prompt()` 中，新增 `{character_state}` 占位符。

注入在 `world_state_context` 之前，因为它比 WorldState 更核心——WorldState 是用户的环境，CharacterState 是角色自己的状态。

### 注入格式

```
【你现在的状态】
情绪：concerned | 精力：0.7
```

**约束**：
- 注入文本**不超过 50 字**
- sleeping=true 时**不注入**（角色在睡觉，不回复）
- mood=calm 时**不注入**（默认状态，不需要提醒 LLM）

### Prompt 影响规则

| State | Prompt 中的影响 |
|-------|----------------|
| mood=concerned | 在 system.yaml 中不新增规则。LLM 从注入文本"情绪：concerned"自行推断"应该更温柔" |
| mood=tired | 同上，LLM 从"精力：0.1"推断"回复应该更短" |
| energy < 0.3 | 同上，LLM 从低精力推断"不要主动扩写" |
| sleeping=true | **不调用 LLM**，直接返回预设回复或延迟回复 |

**设计原则**：State 注入是**提示**而非**规则**。LLM 看到"情绪：concerned"后自行调整回复风格，而不是 Prompt 中写死"如果 concerned 就必须说 XXX"。

---

## 三、State 变化驱动源

### 3.1 用户消息驱动（同步）

| 用户消息 | mood 变化 | energy 变化 |
|---------|----------|------------|
| 表达开心/感谢 | → happy | -0.05 |
| 表达难过/想哭 | → concerned | -0.05 |
| 表达累/疲惫 | → concerned | -0.05 |
| 长消息 (> 25 字) | — | -0.10 |
| 普通消息 | — | -0.05 |

### 3.2 Memory 事件驱动（异步，Phase 4）

| Memory 事件 | mood 变化 |
|-------------|----------|
| Timeline 生成 "用户今天很累" | → concerned |
| Timeline 生成 "用户今天很开心" | → happy |
| RelationshipMemory 新增 "被记住很重要" | → happy |

### 3.3 时间驱动（后台）

| 事件 | 变化 |
|------|------|
| 每小时 | energy -= 0.02 |
| 深夜（23:00-06:00）且 energy < 0.1 | sleeping → true |
| sleeping=true 期间每小时 | energy += 0.15 |
| energy 恢复到 0.6 且用户发消息 | sleeping → false |

---

## 四、与现有模块的交互

### 4.1 与 WorldState 的关系

| | WorldState | CharacterState |
|---|---|---|
| 归属 | 用户的环境 | 角色的内部 |
| 存储 | 会话级，不写数据库 | 数据库持久化 |
| 内容 | 用户的位置/活动/天气 | 角色的情绪/精力/睡眠 |
| Prompt 注入 | `【当前世界】` | `【你现在的状态】` |
| 影响 | LLM 理解用户环境 | LLM 调整回复风格 |

**两者独立运行，互不干扰。** WorldState 回答"用户在哪里"，CharacterState 回答"绘梨衣现在怎么样"。

### 4.2 与 Memory 的关系

```
V3: Memory → Prompt 注入 → LLM 参考
V4: Memory → CharacterState.mood/energy 变化 → Prompt 注入 State → LLM 参考
```

**Phase 1 阶段**：Memory 不直接驱动 State。State 仅由用户消息和时间驱动。
**Phase 4 阶段**：Memory Consolidator 输出结构化影响，驱动 State 变化。

### 4.3 与 Intent 的关系

StateInjector 在 Intent 检测**之后**运行：

```
Intent 检测 → Memory 召回 → State 更新 → Prompt 构建
```

Intent 决定**召回哪些 Memory**，State 决定**以什么风格回复**。两者正交。

---

## 五、数据库 Schema

```sql
CREATE TABLE character_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform VARCHAR(32) NOT NULL,
    platform_user_id VARCHAR(128) NOT NULL,
    mood VARCHAR(32) DEFAULT 'calm' NOT NULL,
    energy FLOAT DEFAULT 1.0 NOT NULL,
    sleeping BOOLEAN DEFAULT 0 NOT NULL,
    mood_updated_at DATETIME,
    energy_updated_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    UNIQUE(platform, platform_user_id)
);

CREATE INDEX ix_character_state_platform_uid ON character_state(platform, platform_user_id);
```

---

## 六、API 变更

### 新增内部接口

```python
# state/store.py

class CharacterStateStore:
    async def get(self, platform: str, platform_user_id: str) -> CharacterState
    async def update(self, platform: str, platform_user_id: str, **kwargs) -> None
    async def decay_energy(self, platform: str, platform_user_id: str, amount: float) -> float
    async def set_sleeping(self, platform: str, platform_user_id: str, sleeping: bool) -> None
    async def get_prompt_text(self, platform: str, platform_user_id: str) -> str
```

### ai/core.py 中的接入点

```python
# 在 chat() 中，Memory 召回之后、Prompt 构建之前

# 6.7. Character State：更新状态 + 获取注入文本
state_store = CharacterStateStore()
char_state = await state_store.get(context.platform, context.platform_user_id)

# 同步更新（用户消息驱动）
char_state = await self._update_state_from_message(char_state, context.message)

# 获取 Prompt 注入文本
character_state_text = await state_store.get_prompt_text(
    context.platform, context.platform_user_id
)

# 7. 构建系统 Prompt（新增 character_state 参数）
system_prompt = self._build_system_prompt(
    ...,
    character_state=character_state_text,
)
```

---

## 七、测试用例

```python
def test_energy_decay_on_chat():
    """每次对话 energy 应衰减。"""

def test_sleeping_blocks_reply():
    """sleeping=true 时不调用 LLM。"""

def test_mood_changes_on_user_sad():
    """用户说"难过" → mood 变为 concerned。"""

def test_state_prompt_text_format():
    """State 注入文本不超过 50 字。"""

def test_energy_recovery_while_sleeping():
    """sleeping=true 时 energy 每小时恢复 0.15。"""
```

---

## 八、不做的事

| 事项 | 原因 |
|------|------|
| State 不记录历史 | mood/energy 只存当前值，历史不重要 |
| State 不驱动主动消息 | Phase 3 才做，Phase 1 只影响回复风格 |
| State 不改变 Persona 定义 | eryi.yaml 不动，State 是运行时状态 |
| sleeping 不做"梦到" | 过度设计，Phase 1 只需要 sleeping 时不回复 |
