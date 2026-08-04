# V4 Stage 0 Safe Refactor Design

> 版本：Draft 1.0 | 日期：2026-08-05
> 基线：`v3.8.1-stable` (cb12bf6) | 测试：37/37
> 目标：安全拆分 `ai/core.py` (1134 行)，行为 100% 一致

---

## 零、设计铁律

| # | 铁律 | 来源 |
|---|------|------|
| 1 | **不改变业务行为** — 所有现有测试断言不变 | Pipeline 分析 |
| 2 | **Step 6a（身份确认）必须在 Step 7（构建 Prompt）前同步完成** | Pipeline 4.1 顺序依赖红线 |
| 3 | **后台任务共享 session 的竞态策略不变**（当前即存在，拆分不放大） | Pipeline 4.3 |
| 4 | **`context_visible` 判定单一来源**（user/assistant 两处写入同值） | Pipeline 4.5 |
| 5 | **LLM 失败语义不变**（返回 `"……"` / 错误文案） | Pipeline 4.4 |
| 6 | **Prompt 内容零改动** — system.yaml 一个字不动 | 冻结规则 |
| 7 | **Memory / Relationship 模块零改动** — 只改 import 位置 | 冻结规则 |

---

## 一、目标模块划分

```
ai/
├── core.py                 # 瘦身后的 Orchestrator（目标 ≤ 350 行）
├── intent.py               # 第一批：Intent 枚举 + detect_intent() + 关键词常量
├── message_formatter.py    # 第一批：_format_user_message()
├── prompt_builder.py       # 第一批：PromptBuilder + _dump_prompt
├── session_manager.py      # 第二批：SessionManager + ConversationSession
├── identity.py             # 第二批：IdentityFlow（5 个方法）
├── world_updater.py        # 第二批：WorldStateUpdater（5a/5b/5c 封装）
├── background_tasks.py     # 第三批：4 个后台任务 + _create_background_task
├── providers/              # 已独立（零改动），定义接口边界
└── __init__.py             # 导出
```

**目标行数**：

| 模块 | 来源（现状） | 目标 |
|------|-------------|:--:|
| intent.py | core.py 36-90 (55 行) | 55 |
| message_formatter.py | core.py 547-570 (24 行) | 24 |
| prompt_builder.py | core.py 618-725 (108 行) | 120 |
| session_manager.py | core.py 119-143 + 657-665 (33 行) | 90 |
| identity.py | core.py 850-1096 (247 行) | 250 |
| world_updater.py | core.py 286-321 + 560-616 (92 行) | 110 |
| background_tasks.py | core.py 727-837 (110 行) | 130 |
| **core.py (Orchestrator)** | **1134** | **≤ 350** |

---

## 二、模块依赖图

```
                    ┌─────────────────────────────┐
                    │      Orchestrator           │
                    │      (core.py, ≤350行)       │
                    │   chat() 编排 + 异常边界      │
                    └─────┬───┬───┬───┬───┬──────┘
             依赖注入(构造时) │   │   │   │   │
        ┌─────────┐ ┌───────┴┐ ┌┴─────┐ ┌┴────┐ ┌─┴────────┐
        │ Session │ │ Prompt  │ │Ident-│ │World│ │ Provider │
        │ Manager │ │ Builder │ │ityFlow│ │Updtr│ │(已独立)  │
        └────┬────┘ └────┬───┘ └──┬───┘ └──┬──┘ └────┬─────┘
             │           │        │        │         │
             ▼           ▼        ▼        ▼         ▼
   ┌────────────┐ ┌──────────┐ ┌────────┐ ┌──────┐ ┌────────────┐
   │ MessageRepo │ │ PromptMgr │ │Profile │ │world_│ │ openai_    │
   │ (database)  │ │ (prompt/) │ │Store   │ │track-│ │ compatible │
   │             │ │ +Character│ │(memory/│ │er.py │ │ .py        │
   │             │ │          │ │stores/)│ │      │ │            │
   └────────────┘ └──────────┘ └────────┘ └──────┘ └────────────┘

   Orchestrator 还持有（不新建文件，直接注入）：
   ├─ memory (MemoryManager)          ← 现有，零改动
   ├─ relationship (RelationshipStore) ← 现有，零改动
   └─ character_loader + prompt_manager ← 现有，零改动

   BackgroundTasks（第三批）依赖：
   └─ SessionManager(共享) + memory + relationship + provider
```

**依赖方向**：全部单向向下。无环。

---

## 三、各模块设计

### 3.1 Orchestrator（core.py 瘦身后）

```python
class AICore:
    """编排器：只做流程编排，不含业务逻辑。"""

    def __init__(self, provider=None, character_loader=None,
                 prompt_manager=None, memory_manager=None):
        self.provider = provider or OpenAICompatibleProvider()
        self.character_loader = character_loader or CharacterLoader()
        self.prompt_manager = prompt_manager or PromptManager()
        self.memory = memory_manager or MemoryManager(SQLiteMemoryStore())
        self.relationship = RelationshipStore()
        self._character = self.character_loader.load(get_settings().character.name)

        # V4 Stage 0 新增：内部组件（构造时组装，行为不变）
        self.sessions = SessionManager()
        self.prompt_builder = PromptBuilder(
            prompt_manager=self.prompt_manager,
            character=self._character,
        )
        self.identity = IdentityFlow()
        self.world = WorldStateUpdater(self.provider)

    async def chat(self, context: ChatContext) -> ChatResponse:
        """编排流水线（20 步，顺序与 V3.8.1 完全一致）。"""
        # Step 0-3: 入口/用户/关系/保存（原样）
        # Step 4: session = self.sessions.get_or_create(...)
        # Step 5: self.world.update(session, context.message)
        # Step 6: intent = detect_intent(...)  ← 来自 intent.py
        # Step 6a: await self.identity.resolve_if_confirmed(platform, uid, message)
        # Step 6b: mem_ctx = await self.memory.get_context(...)
        # Step 6c/6.5: 意图过滤（保留在 orchestrator —— 它是"业务编排"）
        # Step 7: system_prompt = self.prompt_builder.build(...)
        # Step 8: reply = await self.provider.chat(...)  ← 异常边界在此
        # Step 9-12: 原样
        # 返回
```

**关键**：Step 6c（意图过滤）和 Step 6.5 留在 Orchestrator。它们是**编排决策**（根据 intent 决定注入什么），不是纯逻辑。

### 3.2 SessionManager

```python
class SessionManager:
    """会话生命周期管理。纯内存，无 IO 依赖注入点。"""

    def __init__(self):
        self._sessions: dict[str, ConversationSession] = {}

    def _key(self, platform: str, uid: str) -> str:
        return f"{platform}:{uid}"          # 统一 key 构造（修复 3 处重复）

    def get_or_create(self, platform, uid) -> ConversationSession: ...
    def clear(self, platform, uid) -> None: ...
    def get_history(self, platform, uid) -> list[dict]: ...
    async def reload_from_db(self, platform, uid) -> list[dict]: ...
        # 内部调用 MessageRepository.get_recent_history(limit=16)
```

**行为保持**：
- `MAX_HISTORY_MESSAGES = 16` 常量移入本模块
- `ConversationSession` dataclass 原样搬移（含 world_state/active_topics/expression_tracker/_no_match_count）
- 后台摘要对 session 的修改**仍通过**该实例（共享对象引用不变）

### 3.3 PromptBuilder

```python
class PromptBuilder:
    """System Prompt 组装。依赖注入 prompt_manager + character。"""

    def __init__(self, prompt_manager, character):
        self.prompt_manager = prompt_manager
        self.character = character

    def build(self, *, profile_context, memory_context, conversation_summary,
              relationship_tone, timeline_context, relationship_memory_context,
              emotion_trend, intent, world_state, active_topics) -> str:
        """与 _build_system_prompt() 逐行等价。"""
        # 1. identity = self.character.to_identity()      ← 原样
        # 2. world_context = get_world_context()          ← 原样
        # 3. time_context = get_time_context()            ← 原样
        # 4. summary_block / timeline_block / world_state_block / topics_block
        # 5. return self.prompt_manager.render("system", **11 vars)
```

**行为保持**：
- 变量注入顺序与占位符完全一致
- `to_identity()` / `get_world_context()` / `get_time_context()` 调用位置不变
- `_dump_prompt()` 作为静态方法并入本模块

### 3.4 IdentityFlow

```python
class IdentityFlow:
    """身份三级确认流程。V3 设计，行为不变。"""

    # 只依赖 ProfileStore + AsyncSessionLocal（直接注入或内部实例化）

    async def has_pending(self, platform, uid) -> bool: ...
    @staticmethod
    def looks_like_confirmation(message: str) -> bool: ...
    async def resolve_if_confirmed(self, platform, uid, message) -> None:
        """组合方法：has_pending && looks_like_confirmation → resolve。
        ⚠️ 必须由 Orchestrator 在 Step 6a 同步 await —— 红线。"""
    async def get_confirmed_name(self, platform, uid) -> tuple[str|None, str]: ...
    async def create_pending(self, context, intent_name) -> None: ...
```

**红线保护**：`resolve_if_confirmed` 是**同步 await 方法**，文档标注 "MUST be called before build_prompt"。不提供异步/后台变体。

### 3.5 WorldStateUpdater

```python
class WorldStateUpdater:
    """Step 5a/5b/5c 封装。依赖 provider（fallback 用）。"""

    def __init__(self, provider): self.provider = provider

    def apply_rules(self, session, message) -> None:
        # 5a: apply_rules + update_world_state + _no_match_count
        # 5c: active_topics.update
        # (原样逻辑)

    async def llm_fallback(self, session, message) -> None:
        # 5b: needs_llm_fallback → self.provider.chat(极简 prompt)
        # 失败静默（try/except 原样）
```

### 3.6 Provider 接口边界

**决策：不新增抽象基类。** 保持现状签名：

```python
# providers/openai_compatible.py（零改动）
class OpenAICompatibleProvider:
    async def chat(self, messages: list[dict], system_prompt: str | None = None) -> str
    # 属性: model / max_tokens / temperature / client
```

| 边界规则 | 说明 |
|---------|------|
| Provider 是**叶节点** | 只被 Orchestrator + WorldStateUpdater(fallback) + BackgroundTasks 调用 |
| Provider **不反向依赖**任何模块 | 只 import config.settings + openai |
| 拆分阶段**不改变签名** | retry/fallback 是 V4 后续，Stage 0 只划边界 |
| LLM 调用点清单（拆分后仍为 4+1 处） | Step 8 主调用 / Step 5b fallback / 后台 摘要·Timeline·Growth·提取 |

### 3.7 BackgroundTasks（第三批，设计先行）

```python
class BackgroundTasks:
    """4 个后台任务。共享 session 引用（与现状一致）。"""

    def __init__(self, memory, relationship, provider): ...

    async def summarize(self, session) -> None:
        # 原 _summarize_async：LLM 摘要 → session.summary → 截断前 8 条
        # ⚠️ session 是共享引用，截断/追加竞态与现状等价

    async def generate_timeline(self, context, summary) -> None: ...
    async def trigger_growth(self, platform, uid) -> None: ...
    async def extract_profile(self, context, raw_reply) -> None:
        # ⚠️ 参数是 raw reply（非 clean_reply）—— 保持

# 触发点仍在 Orchestrator：
# _create_background_task(BackgroundTasks().summarize(session))
```

---

## 四、迁移顺序

### Phase A — 第一批（零风险，纯搬移）

| 步骤 | 动作 | 验证 |
|:--:|------|------|
| A1 | 新建 `ai/intent.py`：搬 Intent/detect_intent/关键词（core.py 36-90） | 37 测试 |
| A2 | 新建 `ai/message_formatter.py`：搬 _format_user_message（547-570） | 37 测试 |
| A3 | 新建 `ai/prompt_builder.py`：搬 _build_system_prompt + _dump_prompt（618-725） | 37 测试 |
| A4 | core.py 改为 import 调用，删除原实现 | 37 测试 + 52 观察回归 |

**验收**：core.py 减少 ~190 行；测试零改动通过。

### Phase B — 第二批（中风险，有状态）

| 步骤 | 动作 | 验证 |
|:--:|------|------|
| B1 | 新建 `ai/session_manager.py`：搬 ConversationSession + 4 个会话方法 | 37 测试 |
| B2 | 新建 `ai/identity.py`：搬 5 个身份方法，组合 resolve_if_confirmed | 37 测试 + 身份用例回归（"我叫小七"→确认→召回） |
| B3 | 新建 `ai/world_updater.py`：搬 5a/5b/5c 逻辑 | 37 测试 |

**验收**：core.py 减少 ~370 行；身份红线测试（pending→同一轮可见）必须通过。

### Phase C — 第三批（高风险，最后）

| 步骤 | 动作 | 验证 |
|:--:|------|------|
| C1 | 新建 `ai/background_tasks.py`：搬 4 个后台任务 + _create_background_task | 37 测试 |
| C2 | core.py 瘦身为纯 Orchestrator（目标 ≤350 行） | 37 测试 |
| C3 | 完整回归：52 观察用例与 OC-3 数据对比 | 表达基线无差异 |

**验收**：core.py ≤ 350 行；`chat()` 方法体无超过 5 行的独立逻辑块。

---

## 五、红线检查表（每 Phase 完成后核对）

| # | 红线 | 验证方式 |
|---|------|---------|
| 1 | 37/37 测试通过，断言零改动 | pytest |
| 2 | 身份确认同轮可见 | 测试：pending 创建 → resolve → 同一轮 Prompt 含名字 |
| 3 | context_visible user/assistant 同值 | 单测断言 |
| 4 | LLM 失败返回 "……" | 现有 test_api_chat 覆盖 |
| 5 | Prompt 渲染结果与拆分前逐字符一致 | 快照测试（拆分前 dump 一次，拆分后对比） |
| 6 | system.yaml / memory / relationship 零改动 | git diff 仅 ai/ 下新增文件 |

---

## 六、不做的事

| 事项 | 原因 |
|------|------|
| 不引入 Provider 抽象基类 | Stage 0 只划边界，不重构 Provider |
| 不新增 retry/fallback | V4 后续阶段 |
| 不解决 session 竞态 | 现状即存在，拆分不放大；V4 再定策略 |
| 不拆 world_tracker.py (599 行) | 已独立，可后续评估 |
| 不改 PromptBuilder 的渲染输出 | 逐字符一致是验收标准 |
| 不动 memory/、relationship/、database/、prompt/ 任何文件 | 冻结规则 |

---

## 七、完成定义（Stage 0 Done）

```
✅ core.py ≤ 350 行（Orchestrator 纯编排）
✅ 6 个新模块文件：intent / message_formatter / prompt_builder / session_manager / identity / world_updater / background_tasks
✅ 37/37 测试通过（断言零改动）
✅ 52 观察用例与 OC-3 无差异
✅ Prompt 快照逐字符一致
✅ git diff 不触及 memory/ relationship/ prompt/templates/ database/
```
