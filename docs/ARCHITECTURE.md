# 系统架构文档

> 修改代码前必读。回答"系统由什么组成，各模块如何协作"。

---

## 整体架构图

```
┌─────────────────────────────────────────────────────────┐
│  adapters/          api/            agent/              │
│  Telegram Bot       HTTP API        主动消息             │
│  (220行)            (65行)          (509行)             │
├─────────────────────────────────────────────────────────┤
│                   ai/core.py (1122行)                    │
│  消息路由中枢：Intent检测 → Memory召回 → Prompt构建 → LLM调用 │
├──────────────┬──────────────┬──────────────┬────────────┤
│  memory/     │  prompt/     │  character/  │  ai/providers/
│  记忆系统     │  Prompt管理   │  角色加载     │  LLM Provider │
│  (2495行)    │  (122行)     │  (211行)     │  (91行)       │
├──────────────┴──────────────┴──────────────┴────────────┤
│  database/           config/           utils/           │
│  数据层 (626行)      配置 (160行)       工具 (170行)      │
└─────────────────────────────────────────────────────────┘
```

## 核心模块

### ai/ — AI Core

| 文件 | 行数 | 职责 |
|------|------|------|
| `ai/core.py` | 1122 | 消息处理中枢：Intent 检测、Memory 召回调度、意图过滤、Prompt 构建、LLM 调用、后台任务触发 |
| `ai/world_tracker.py` | 599 | 规则引擎：WorldState（位置/活动/温度/天气/情绪）、ActiveTopics（话题分数衰减）、ExpressionTracker |
| `ai/providers/openai_compatible.py` | 91 | LLM Provider 封装（DeepSeek / OpenAI 兼容协议） |

**依赖方向**：ai → memory + prompt + character + database + config

**修改影响**：`ai/core.py` 是 1122 行的上帝对象。修改 `chat()` 方法会影响全部消息流。重大改动前需评估影响范围。

### memory/ — 记忆系统

包含 6 个 Store + 5 个 Processing 文件，共 ~2500 行。

**存储层（Stores）**：

| 文件 | 职责 | 对应数据库表 |
|------|------|------------|
| `stores/sqlite_store.py` | LongMemory CRUD + 关键词搜索 | `memory_records` |
| `stores/profile_store.py` | Profile CRUD + 冲突检测 | `user_profiles` + `profile_history` |
| `stores/relationship_store.py` | Metrics + Timeline 管理 | `relationship_metrics` + `relationship_timeline` |
| `stores/relationship_memory_store.py` | 关系理解 CRUD + 衰减 | `relationship_memories` |

**处理层（Processing）**：

| 文件 | 职责 |
|------|------|
| `extractor.py` | LLM 提取用户 Profile + LongMemory + source 标记 |
| `retriever.py` | Profile 常驻加载 + LongMemory 关键词搜索 |
| `summarizer.py` | 对话滚动摘要（触发阈值 12 条消息） |
| `consolidator.py` | Timeline → RelationshipMemory 提炼 |
| `relationship_growth.py` | Pattern Discovery + Memory Merge + Emotion Trend |
| `manager.py` | MemoryManager：统一入口，协调所有子模块 |

**六层记忆架构**：

```
Profile (常驻注入) → Relationship (Timeline + Memory) → LongMemory (按需搜索)
→ RecentContext (会话窗口) → WorldState (规则引擎) → ActiveTopics (分数衰减)
```

**修改影响**：Store 层修改影响数据库写入；Processing 层修改影响 LLM 调用频率和 Prompt 内容。

### prompt/ — Prompt 管理

| 文件 | 职责 |
|------|------|
| `prompt/manager.py` | 模板加载 + 变量渲染（`str.format()`） |
| `templates/system.yaml` | 主 System Prompt 模板 |
| `templates/memory.yaml` | Memory 提取 Prompt 模板 |

**Persona 控制**：`system.yaml` 是唯一的行为控制入口（V3.7 后收敛至此）。`character/eryi.yaml` 仅提供 `{identity}` 占位符内容。

### character/ — 角色系统

| 文件 | 职责 |
|------|------|
| `character/loader.py` | YAML 角色加载 + `to_identity()` 生成 |
| `characters/eryi.yaml` | 绘梨衣角色定义 |

**`to_identity()` 实际注入到 Prompt 的内容**：仅 YAML 中 `personality` 第一行 + `speaking_style` 第一有效行（约 3 行）。其余内容不进入实际 Prompt。

### database/ — 数据层

8 个 ORM 模型，映射 8 个 SQLite 表：

| 模型 | 表 | 用途 |
|------|-----|------|
| `User` | `users` | 用户注册 |
| `Message` | `messages` | 聊天记录（含 `context_visible` 过滤） |
| `MemoryRecord` | `memory_records` | LongMemory（含 `source` + `evidence`） |
| `UserProfile` | `user_profiles` | Profile 身份信息 |
| `ProfileHistory` | `profile_history` | Profile 变更历史（含 `pending`/`confirmed`） |
| `RelationshipMetrics` | `relationship_metrics` | 关系指标（聊天次数、连续天数） |
| `TimelineEntry` | `relationship_timeline` | 共同经历时间线 |
| `RelationshipMemory` | `relationship_memories` | 关系理解（含衰减 `decay_score`） |

**依赖方向**：database → config（零 project 内依赖，最底层）

### adapters/ — 平台适配器

| 文件 | 职责 |
|------|------|
| `adapters/telegram/bot.py` | Telegram Bot：消息接收 → AICore.chat() → 回复发送 |

**依赖方向**：adapters → ai + config。平台适配层不包含 AI 逻辑。

### agent/ — 主动消息

| 文件 | 职责 |
|------|------|
| `agent/scheduler.py` | 定时调度 |
| `agent/decision.py` | 概率决策（bond + 冷却 + 上限） |
| `agent/generator.py` | 主动消息生成 |
| `agent/sender.py` | 消息发送 |
| `agent/state.py` | Agent 状态（AgentState ORM） |

---

## 数据流向

### 消息处理主流程

```
Telegram/CLI/HTTP 消息
  ↓
AICore.chat()
  ├─ 1. UserRepository.get_or_create()              → users 表
  ├─ 2. RelationshipStore.touch()                    → relationship_metrics 表
  ├─ 3. MessageRepository.save()                     → messages 表
  ├─ 4. MemoryRetriever.retrieve()                   → Profile 常驻 + LongMemory 搜索
  ├─ 5. Rule Engine (WorldState + ActiveTopics)      → 内存
  ├─ 6. Intent 检测 → 选择性注入过滤
  ├─ 7. Pending Identity 检查
  ├─ 8. RelationshipMemory + EmotionTrend 加载       → relationship_memories 表
  ├─ 9. PromptManager.render("system", ...)           → system.yaml 模板
  ├─ 10. OpenAICompatibleProvider.chat()              → DeepSeek API
  ├─ 11. render_for_storage() 清洗 → MessageRepository.save()  → messages 表
  └─ 12. 异步后台任务:
       ├─ _summarize_async()          → 内存（滚动摘要）
       ├─ _generate_timeline_async()  → relationship_timeline 表
       ├─ _trigger_growth_if_needed() → relationship_memories 表
       └─ _extract_profile_async()    → user_profiles 表 + memory_records 表
```

### 身份确认流程

```
用户: "我叫夏离萤"
  → _detect_profile_intent() → NAME_INTRO
  → _should_extract() → False（阻断 LLM 提取）
  → _create_pending_identity() → profile_history (status=pending)
  → context_visible=False（不注入 LLM）

用户: "对，就叫这个"
  → _has_pending_identity() → True
  → _looks_like_confirmation() → True
  → _resolve_pending_identity()
    → profile_history.status → "confirmed"
    → user_profiles.name → "夏离萤"
```

---

## 模块依赖关系

```
config/ (0 入向)
  ↑
database/ (54 入向，全项目最被依赖)
  ↑
memory/stores/ (仅被 memory/ 内部依赖)
  ↑
memory/processing/ (仅被 ai/core 依赖)
  ↑
ai/core/ (被 adapters/ api/ agent/ scripts/ 依赖)
  ↑
adapters/ api/ agent/ scripts/ (顶层，不被其他模块依赖)
```

**无循环依赖。** 分层严格：config → database → memory → ai → adapters。

---

## 新增功能应该放哪里

| 需求 | 应该放 | 原因 |
|------|--------|------|
| 调整角色语气 | `system.yaml` | 表达层控制入口 |
| 新增记忆类型 | `database/models/` + `memory/stores/` | 数据模型 + 存储 |
| 新增平台接入 | `adapters/` 新建子目录 | 适配器模式 |
| 修改记忆搜索方式 | `memory/stores/sqlite_store.py` | Store 层 |
| 修改 LLM Provider | `ai/providers/` | Provider 层 |
| 后台定时任务 | `agent/` | 主动消息层 |
| API 接口变更 | `api/v1/` | HTTP API 层 |
| 新增工具 | `tools/builtin/` + 注册到 `ai/core.py` | 工具系统（待集成） |

### 不要放的地方

- 不要在 `adapters/` 中放 AI 逻辑
- 不要在 `ai/core.py` 中新增超过 20 行的方法（应该抽到独立模块）
- 不要在 `memory/manager.py` 中直接操作数据库（应该通过 Store）
- 不要在 `system.yaml` 中添加"不要使用：X, Y, Z"式黑名单
