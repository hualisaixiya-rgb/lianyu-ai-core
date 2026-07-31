# V4 设计前置分析

> 日期：2026-07-31 | 基线：V3.8 Stable (`v3.8-stable`)
> 性质：纯分析，不编码。为 V4 架构设计提供依据。

---

## 一、当前 V3 架构瓶颈

### 1.1 结构性瓶颈

| 瓶颈 | 位置 | 严重度 | 后果 |
|------|------|:--:|------|
| **上帝对象** | `ai/core.py` 1,112 行 | 🔴 高 | 每新增功能就在中间插入一步。chat() 方法 27 个步骤堆在一个方法里。修改任一环节需要理解全部 1,112 行 |
| **LLM 调用链过长** | chat → 提取 → 摘要 → Timeline → Growth → Consolidation | 🟡 中 | 一条用户消息触发 6 次 LLM 调用（1 主 + 5 后台），误差累积 |
| **Memory 仅做上下文填充** | 整个 memory/ 模块 | 🟡 中 | Timeline / Profile / LongMemory / RelationshipMemory 全部通过 Prompt 注入，LLM 自由参考——是否"真正使用"不可控 |
| **角色被动** | 整个系统 | 🟡 中 | 只有用户输入 → AI 回复，没有内部状态驱动的行为 |
| **Persona 是静态文本** | `eryi.yaml` | 🟢 低 | 角色设定从未更新，也不会根据用户互动进化 |

### 1.2 功能瓶颈

| 瓶颈 | 表现 | 根因 |
|------|------|------|
| 角色暴露 AI 属性 | "我不用睡觉""我不需要呼吸" | 角色没有内部状态概念。没有 `sleeping` 字段，LLM 就会推断"我不需要睡觉" |
| 角色无自我 | "只要能看到你笑，就已经很满足了" | Persona 只有 likes/dislikes，没有 opinions/habits — 角色没有想说"我"的时候 |
| 角色围绕用户旋转 | 所有回复指向用户 | 没有 SelfPersonality 支撑"我是谁，我喜欢什么，我怎么想" |
| Memory 不能驱动行为 | 记忆存在但可能被 LLM 忽略 | 无结构化影响链路：Memory → State → Behavior |

### 1.3 工程瓶颈

| 瓶颈 | 现状 | 影响 |
|------|------|------|
| 测试覆盖不均匀 | 32 测试集中在 chat/prompt/character/config | Memory/Relationship/Voice/Agent 模块测试覆盖薄弱 |
| `except Exception: pass` 残存 | V3.8 已加日志但仍有 2 处在 database/session 中 | 低风险但非零 |
| 无性能基准 | 从未测量 chat() 全流程耗时 | V4 新增 State/Self 注入后，Prompt 长度增加，需监控 |

---

## 二、长期人格模拟下一阶段需求

从项目定位出发：「面向虚拟角色的长期人格与人工生命模拟系统」，V3 完成了「能聊天」，V4 需要完成「像活的」。

### 2.1 角色"活着"的要素

| 要素 | V3 状态 | V4 目标 |
|------|---------|---------|
| 状态感知 | ❌ 无 | 有时刻变化的 mood/energy/sleeping |
| 自我意识 | ❌ 无（人格是提示词） | 有 preferences/opinions/habits/expressions |
| 时间感 | ⚠️ 有（TimeSystem 提供当前时间） | 有时间流逝感（energy 衰减、sleeping 切换） |
| 记忆影响 | ⚠️ 有（Prompt 注入） | 记忆改变状态，状态改变行为 |
| 关系演化 | ⚠️ 有（Metrics/Timeline） | 关系深度基于共同经历，而非分数 |
| 主动行为 | ❌ 无（agent/ 预留但未启用） | 基于状态+习惯+关系的前提条件触发 |

### 2.2 用户期望映射

从三个案例中提取的用户期望：

| 用户行为 | 期望角色表现 | 需要的 V4 能力 |
|---------|------------|--------------|
| "我又醒了" | 角色也刚醒，有困意的感觉 | CharacterState.sleeping / energy |
| "你都不为自己考虑的吗" | 角色有自己的偏好、想法 | SelfPersonality |
| 凌晨聊天 | 角色偶尔主动找用户 | Initiative（最后做） |
| "你还记得我们第一次聊天吗" | 角色能引用具体事件 | Relationship Growth |

---

## 三、可能的 V4 方向

### 3.1 方向 A：深度人格（保守路线）

```
目标：让绘梨衣更像"人"，但不改变交互模式

改动范围：
  - SelfPersonality（角色偏好+观点+习惯）
  - CharacterState（mood/energy/sleeping）
  - 无 Initiative（被动回复模式不变）

优点：风险最低，改动最小
缺点：不会主动行为，交互模式与 V3 相同
时间：~2 周
```

### 3.2 方向 B：生命模拟（中等路线）

```
目标：角色有状态、有关系历史、能主动行为

改动范围：
  - SelfPersonality + CharacterState + MemoryEvolution
  - Relationship Growth（深化关系系统）
  - Initiative（默认关闭）+ User Habit

优点：实现"人工生命模拟"的完整愿景
缺点：改动较大，Initiative 风险高
时间：~4-6 周（分 6 个 Stage）
```

### 3.3 方向 C：Agent 化（激进路线）

```
目标：角色可以自己决定做什么、说什么、什么时候说

改动范围：
  - 全部 V4 Phase
  - Tools 接入聊天（calculator/read_image）
  - 多平台主动消息
  - 角色自主决策引擎

优点：最接近"人工生命"
缺点：偏离"绘梨衣"角色定位，可能变成通用 Agent
时间：8+ 周
风险：极高——角色可能失控，用户可能反感
```

### 3.4 推荐：方向 B（中等路线）

**V4 冻结的 Phase 1-6 等同于方向 B。**

理由：
- 方向 A（被动聊天优化）可以实现，但用户已经在问"你都不为自己考虑的吗"——需要自我人格
- 方向 B 在 V3 基础上增加 State/Self/Memory Evolution/Initiative 四层，是自然演进
- 方向 C 的风险在于 Tools 接入会破坏绘梨衣的沉浸感（一个温柔安静的角色的不应该突然变成计算器）

---

## 四、V4 不能妥协的原则

| 原则 | 说明 |
|------|------|
| Persona 核心不可变 | eryi.yaml 的 personality/speaking_style 不动。V4 通过扩展（self_personality）添加自我人格，而非覆盖 |
| 表达基线不退化 | V3.7 验证过的日常问候/情感/文学诱导三类表达模式，V4 不能破坏 |
| Memory 只做加法 | 现有 Memory 提取/召回/存储逻辑不修改。V4 通过新增 `evolution.py` 做影响链路 |
| Initiative 默认关闭 | 主动消息必须用户主动开启，且可随时关闭 |
| 一次一个变量 | 每个 Phase 完成→测试全过→才能开始下个 Phase |
| 可回退 | 每个 Stage 独立回退，不影响其他 Stage |

---

## 五、V4 与 V3 的架构兼容边界

### V4 新增但不修改 V3 的模块

| V4 模块 | 对应的 V3 模块 | 关系 |
|---------|-------------|------|
| `state/` 目录 | `ai/world_tracker.py` | State 是角色内部状态，WorldState 是用户环境。共存。 |
| `memory/evolution.py` | `memory/consolidator.py` | Consolidator 做 Timeline→RelationshipMemory 提炼。Evolution 做 Timeline→CharacterState 影响。互补。 |
| `character/self_personality.py` | `character/loader.py` | Loader 加载 YAML（扩展现有加载逻辑，新增 self_personality 字段）。 |
| `database/models/character_state.py` | `database/models/` | 新增表，不修改现有 8 张表。 |
| `ai/state_injector.py` | `ai/core.py` | V4 Stage 0 拆分 core.py 时新增，不在 V3 期间改动。 |

### V4 必须修改的 V3 模块

| V3 模块 | 修改 | 风险 |
|---------|------|:--:|
| `ai/core.py` | Stage 0 拆分为 Layer | 高（37 个现有步骤→重新分配到各 Layer） |
| `prompt/templates/system.yaml` | 新增 `{character_state}` 和 `{self_personality}` 占位符 | 低（只追加两行） |
| `character/characters/eryi.yaml` | 新增 `self_personality` 字段 | 低（追加，不覆盖现有字段） |
| `character/loader.py` | 解析 self_personality 字段 | 低（扩展现有 parse 逻辑） |

---

## 六、V4 前置条件检查

| 条件 | 状态 | 说明 |
|------|:--:|------|
| V3.8 基线稳定 | ✅ | 32 测试全过，5 项修复完成 |
| 表达基线冻结 | ✅ | system.yaml V3.7 冻结 |
| 架构文档完整 | ✅ | V4_DESIGN + 5 份 Phase 文档 + 验收测试 |
| 审查流程就绪 | ✅ | REVIEW_SYSTEM.md + REVIEW_TEMPLATE.md |
| Git tag 已创建 | ✅ | `v3.8-stable` |
| `ai/core.py` 1,112 行 | ⚠️ | V4 Stage 0 必须先拆分 |

**结论**：除 `ai/core.py` 拆分外，所有前置条件已满足。V4 Stage 0 是必须的第一步。
