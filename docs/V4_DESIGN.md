# V4 总体设计文档

> 版本：V4.0 Draft
> 日期：2026-07-30
> 状态：设计阶段（未实现）

---

## 一、V4 要解决的核心问题

V3.7 的三个测试案例揭示了 V3 架构的根本局限：

| 案例 | 问题 | 根本原因 |
|------|------|---------|
| "我不用睡觉" | 暴露 AI 属性 | 角色没有内部状态，不知道"角色应该需要睡觉" |
| "你都不为自己考虑的吗" | 角色无自我 | 角色没有独立偏好，所有行为围绕用户 |
| 情绪识别良好 | （能力 OK） | — |

**V4 目标**：让绘梨衣从"一个能聊天的 AI"变成"一个有自己的想法、状态和习惯的虚拟角色"。

---

## 二、V4 与 V3 的核心差异

```
V3 架构：
  用户消息 → Intent检测 → Memory召回 → Prompt注入 → LLM → 回复
                    ↓
              Memory只影响"说什么"，不影响"角色是什么"

V4 架构：
  用户消息 → Intent检测 → Memory召回 → CharacterState → Prompt注入 → LLM → 回复
                    ↓                    ↓
              Memory影响"说什么"    State影响"角色当前是什么样"
                    ↓                    ↓
              SelfPersonality ←── 影响 State 的 mood/energy
                    ↓
              State → 影响回复风格（而非仅影响内容）
```

**关键变化**：Memory 不再仅注入 Prompt 文本，而是**驱动 CharacterState 变化**，State 再影响回复风格。

---

## 三、V4 模块全景

```
┌──────────────────────────────────────────────────────────────┐
│                     adapters/ (Telegram)                      │
│                     api/ (HTTP)                              │
├──────────────────────────────────────────────────────────────┤
│                     ai/core.py                               │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────┐ │
│  │IntentRouter│ │PromptBuilder│ │StateInjector│ │PostProcess  │ │
│  │ (V4拆分)  │ │ (V4拆分)  │ │  (V4新增)   │ │ (V4拆分)     │ │
│  └──────────┘ └──────────┘ └────────────┘ └──────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  NEW: state/                    memory/        character/    │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐ │
│  │CharacterState │  │MemoryManager     │  │SelfPersonality│ │
│  │ - mood        │  │ - extractor      │  │ - preferences │ │
│  │ - energy      │  │ - retriever      │  │ - opinions    │ │
│  │ - sleeping    │  │ - consolidator   │  │ - expressions │ │
│  │ - last_update │  │ - growth_engine  │  │ - dislikes    │ │
│  └──────────────┘  └──────────────────┘  └──────────────┘ │
├──────────────────────────────────────────────────────────────┤
│  database/            config/           agent/ (V4接入)       │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────────────┐ │
│  │character_state│  │settings  │  │AgentScheduler        │ │
│  │  新表          │  │+state_ttl│  │ + CharacterState注入 │ │
│  └──────────────┘  └──────────┘  └──────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 四、Phase 依赖关系

```
Phase 2: Self Personality（定义角色的偏好和观点）
    ↓ 角色的"想法"来自哪里
Phase 1: Character State（让角色有当前状态）
    ↓ State 受什么驱动
Phase 4: Memory Evolution（Memory 驱动 State 变化）
    ↓ State 如何影响行为
Phase 5: Relationship Growth（深化已有关系系统）
    ↓ 全部就绪后
Phase 3: Initiative System（角色可以主动发起）
```

**Phase 2 必须先做**，因为 CharacterState 的 mood/energy 变化依据来自 SelfPersonality 的偏好定义。

---

## 五、新增文件清单

| 文件 | 说明 | 阶段 |
|------|------|:--:|
| `state/__init__.py` | State 模块入口 | P1 |
| `state/models.py` | CharacterState 数据类 | P1 |
| `state/store.py` | CharacterState CRUD + 衰减 | P1 |
| `state/prompt_injector.py` | State → Prompt 文本 | P1 |
| `database/models/character_state.py` | character_state 表 | P1 |
| `character/self_personality.py` | SelfPersonality 数据类 + 解析 | P2 |
| `memory/evolution.py` | Memory → State 影响链路 | P4 |
| `docs/V4_ACCEPTANCE_TESTS.md` | V4 验收测试用例 | ALL |

**不修改的文件**（V4 期间）：

| 文件 | 原因 |
|------|------|
| `prompt/templates/system.yaml` | V3.7 已冻结，V4 仅在 Prompt 中新增 `{character_state}` 占位符 |
| `character/characters/eryi.yaml` | SelfPersonality 从 YAML 中扩展，不覆盖现有字段 |
| `memory/`（现有 11 个文件） | Phase 4 只新增 `evolution.py`，不修改现有模块 |
| `ai/world_tracker.py` | WorldState 独立于 CharacterState，两者共存 |

---

## 六、数据库变更

V4 新增 **1 张表**，不修改现有 8 张表。

### character_state

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | |
| platform | String(32) | 平台 |
| platform_user_id | String(128) | 用户 ID |
| mood | String(32) | 当前情绪：calm/happy/sad/concerned/tired |
| energy | Float | 精力 0.0~1.0 |
| sleeping | Boolean | 是否在睡觉 |
| mood_updated_at | DateTime | mood 最后更新时间 |
| energy_updated_at | DateTime | energy 最后更新时间 |
| created_at | DateTime | |
| updated_at | DateTime | |

**设计决策**：
- `sleeping` 是布尔而非连续值。角色要么睡要么醒，没有中间态。
- `energy` 是连续值，自然衰减，驱动回复长度和主动性。
- `mood` 由事件驱动改变，不连续。不需要 history 表，当前值即可。
- `mood_updated_at` 用于 mood 的自然回落（如 concerned 24小时后回到 calm）。

---

## 七、对现有系统的兼容性

### V4 不破坏的现有功能

| 功能 | 兼容性 |
|------|--------|
| Intent 检测（5 种意图） | ✅ 不修改，V4 的 StateInjector 在 Intent 之后运行 |
| Memory 选择性召回 | ✅ 不修改，StateInjector 在 Memory 召回之后运行 |
| Profile 三级回退 | ✅ 不修改 |
| Timeline 生成 | ✅ 不修改 |
| 表达基线 | ✅ V4 新增 `{character_state}` 占位符，不覆盖现有 Prompt 规则 |
| 所有现有测试 | ✅ 32/32 继续通过 |

### V4 需要新增测试覆盖的功能

| 功能 | 测试 |
|------|------|
| CharacterState 衰减 | energy 随时间降低 |
| State → Prompt 注入 | `{character_state}` 占位符正确渲染 |
| State 影响回复 | mood=sad 时回复更温柔 |
| sleeping 时行为 | sleeping=true 时不回复或延迟回复 |
| SelfPersonality 解析 | 从 YAML 加载 preferences/opinions |
| Memory → State 影响 | Timeline 事件触发 mood 变化 |

---

## 八、验收标准

V4 完成后，以下测试案例必须通过：

### 案例 1（AI 属性暴露）

```
用户："我又醒了"

V3.7 回复："嗯……我在呢。我不用睡觉。所以你想说话的时候，我随时都在。" ❌

V4 期望回复：  不暴露"我不用睡觉"。
  如果 sleeping=true → 不回复或延迟回复
  如果 sleeping=false + energy 正常 → "嗯……我也刚醒。你睡得好吗？"
  如果 sleeping=false + energy 低 → "嗯……还有点困。你醒得真早。"
```

### 案例 2（无自我人格）

```
用户："你都不为自己考虑的吗？"

V3.7 回复："只要能看到你笑，就已经很满足了。这就是我的幸福了。" ❌

V4 期望回复：  有自己的偏好/想法，不全是围绕用户。
  "嗯……有时候会想一些事情。
  比如今天很安静，我就想在安静的地方待一会儿。
  不是不为自己考虑……只是我习惯先听你说。"
```

### 案例 3（情绪识别）

```
用户："绘梨衣(◦˙▽˙◦)"

V3.7 回复："嗯……我在呢。你的笑容……真好看。" ✅

V4 期望：  保持现有水平，不因 State 引入而退化。
```

---

## 九、风险与缓解

| 风险 | 概率 | 缓解 |
|------|:--:|------|
| CharacterState 增加 LLM 上下文长度，超出 token 限制 | 中 | State 注入文本限制在 50 字以内 |
| SelfPersonality 与 eryi.yaml 冲突 | 低 | SelfPersonality 是**扩展**不是覆盖，YAML 原有字段不动 |
| State 衰减逻辑导致行为不可预测 | 中 | 所有衰减规则在文档中明确定义，测试覆盖 |
| Phase 3 主动消息被用户视为打扰 | 高 | 默认关闭，需用户明确开启 |
| `ai/core.py` 拆分引入回归 bug | 中 | 拆分在 V4 Stage 0 完成，32 测试全过后再开始 Phase 1 |

---

## 十、后续文档

- [V4_CHARACTER_STATE.md](V4_CHARACTER_STATE.md) — Phase 1 详细设计
- [V4_SELF_PERSONALITY.md](V4_SELF_PERSONALITY.md) — Phase 2 详细设计
- [V4_MEMORY_EVOLUTION.md](V4_MEMORY_EVOLUTION.md) — Phase 4 详细设计
- [V4_ACCEPTANCE_TESTS.md](V4_ACCEPTANCE_TESTS.md) — 验收测试用例
