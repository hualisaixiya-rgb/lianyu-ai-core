# V4 Stage 0 Safe Refactor Design

> 版本：Draft 2.0 | 日期：2026-08-05
> 基线：`v3.8.1-stable` (cb12bf6) | 测试：37/37
> 目标：安全拆分 `ai/core.py` (1134 行)，行为 100% 一致
> 修订：整合 Kimi 架构反馈（Identity 归属 / 并发策略 / PromptContext / 行为一致性测试 / 日志观测）

---

## 零、设计铁律

| # | 铁律 | 来源 |
|---|------|------|
| 1 | **不改变业务行为** — 所有现有测试断言不变 | Pipeline 分析 |
| 2 | **Step 6a（身份确认）必须在 Step 7（构建 Prompt）前同步完成**，且红线落在 Orchestrator 内部 | Pipeline 4.1 + Kimi #1 |
| 3 | **后台任务并发策略：选 A（asyncio.Lock）**，锁不跨 await 持锁 | Kimi #2 |
| 4 | **`context_visible` 判定单一来源**（user/assistant 两处写入同值） | Pipeline 4.5 |
| 5 | **LLM 失败语义不变**（返回 `"……"` / 错误文案） | Pipeline 4.4 |
| 6 | **Prompt 内容零改动** — system.yaml 一个字不动 | 冻结规则 |
| 7 | **Memory / Relationship 模块零改动** — 只改 import 位置 | 冻结规则 |
| 8 | **每批拆分后运行行为一致性测试**（输出 + DB checksum） | Kimi #4 |

---

## 一、目标模块划分

```
ai/
├── core.py                 # 瘦身后的 Orchestrator（目标 ≤ 350 行）
├── intent.py               # 第一批：Intent 枚举 + detect_intent() + 关键词常量
├── message_formatter.py    # 第一批：_format_user_message()
├── prompt_builder.py       # 第一批：PromptBuilder(PromptContext) + _dump_prompt
├── session_manager.py      # 第二批：SessionManager + ConversationSession + session_lock
├── identity.py             # 第二批：IdentityFlow（Orchestrator 子组件，非独立层）
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
| session_manager.py | core.py 119-143 + 657-665 (33 行) | 100（含锁） |
| identity.py | core.py 850-1096 (247 行) | 250 |
| world_updater.py | core.py 286-321 + 560-616 (92 行) | 110 |
| background_tasks.py | core.py 727-837 (110 行) | 140 |
| **core.py (Orchestrator)** | **1134** | **≤ 350** |

---

## 二、模块依赖图

```
                    ┌─────────────────────────────┐
                    │      Orchestrator           │
                    │      (core.py, ≤350行)       │
                    │   chat() 编排 + 异常边界      │
                    │   + IdentityFlow 子组件       │
                    └─────┬───┬───┬───┬───┬──────┘
             依赖注入(构造时) │   │   │   │   │
        ┌─────────┐ ┌───────┴┐ ┌┴─────┐ ┌┴────┐ ┌─┴────────┐
        │ Session │ │ Prompt │ │Ident-│ │World│ │ Provider │
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
   └─ SessionManager(经 session_lock 访问) + memory + relationship + provider
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
        self.identity = IdentityFlow()          # Orchestrator 子组件
        self.world = WorldStateUpdater(self.provider)

    async def chat(self, context: ChatContext) -> ChatResponse:
        """编排流水线（20 步，顺序与 V3.8.1 完全一致）。"""
        # Step 0-3: 入口/用户/关系/保存（原样）
        # Step 4: session = self.sessions.get_or_create(...)
        # Step 5: self.world.update(session, context.message)
        # Step 6: intent = detect_intent(...)  ← 来自 intent.py
        # Step 6a: await self.identity.resolve_if_confirmed(platform, uid, message)
        #           ← 红线：必须在 Step 7 前。IdentityFlow 是子组件，红线在 Orchestrator 内部
        # Step 6b: mem_ctx = await self.memory.get_context(...)
        # Step 6c/6.5: 意图过滤（保留在 orchestrator —— 编排决策）
        # Step 7: ctx = self._assemble_prompt_context(...)   ← Orchestrator 组装 PromptContext
        #         system_prompt = self.prompt_builder.build(ctx)
        # Step 8: reply = await self.provider.chat(...)  ← 异常边界在此
        # Step 9-12: 原样
        # 返回
```

**关键**：
- Step 6c（意图过滤）和 Step 6.5 留在 Orchestrator（编排决策）
- `_assemble_prompt_context()` 是 Orchestrator 的私有方法 —— 负责把 11 个变量组装成 PromptContext

### 3.2 SessionManager（含并发策略）

```python
class SessionManager:
    """会话生命周期管理。纯内存。

    并发策略（Kimi #2 决策 A）：asyncio.Lock 保护 session 可变操作。
    约束：锁不跨 await 持锁 —— 主流程在 await LLM 时不持锁，
    后台任务在 LLM 摘要完成后才获取锁写 session。
    """

    def __init__(self):
        self._sessions: dict[str, ConversationSession] = {}

    def _key(self, platform: str, uid: str) -> str:
        return f"{platform}:{uid}"          # 统一 key 构造（修复 3 处重复）

    def get_or_create(self, platform, uid) -> ConversationSession: ...
    def clear(self, platform, uid) -> None: ...
    def get_history(self, platform, uid) -> list[dict]: ...
    async def reload_from_db(self, platform, uid) -> list[dict]: ...
        # 内部调用 MessageRepository.get_recent_history(limit=16)


# ConversationSession 增加锁字段：
@dataclass
class ConversationSession:
    platform: str
    platform_user_id: str
    messages: list[dict] = field(default_factory=list)
    loaded_from_db: bool = False
    summary: str = ""
    pending_count: int = 0
    world_state: WorldState | None = None
    active_topics: ActiveTopics | None = None
    expression_tracker: ExpressionTracker | None = None
    _no_match_count: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # 新增
```

**锁的使用规则**：

| 操作 | 是否需要锁 | 原因 |
|------|:--:|------|
| 主流程 append user/assistant 消息 | ❌ | 同步操作，在 await LLM 之前完成，无并发窗口 |
| 后台摘要截断 session.messages | ✅ | 可能与下一轮主流程 append 并发 |
| 后台摘要写 session.summary | ✅ | 同上 |
| 主流程读 session.summary | ❌ | 读操作，短暂窗口可接受（与现状等价） |

**锁定模式**：

```python
# 后台任务（_summarize_async 改造后）
async def summarize(self, session) -> None:
    new_summary = await self._llm_summarize(...)   # 不持锁 await LLM
    async with session._lock:                      # 仅临界区持锁
        session.summary = new_summary
        session.messages = session.messages[8:]
        session.pending_count = 0
```

**行为等价性**：锁是**防御性**的。当前单用户场景下竞态窗口几乎不会命中，加锁不改变输出，只消除"隐式风险→分布式 Bug"的隐患。

### 3.3 PromptBuilder（PromptContext 设计）

```python
@dataclass
class PromptContext:
    """Prompt 渲染所需的全部上下文。11 个字段平铺。"""
    identity: str                    # character.to_identity()
    current_time: str                # get_time_context()
    world_context: str               # get_world_context()
    profile_context: str             # 来自 mem_ctx
    memory_context: str              # 来自 mem_ctx
    conversation_summary: str        # summary_for_prompt
    relationship_tone: str           # 恒为空（预留）
    timeline_context: str            # timeline_for_prompt
    relationship_memory_context: str # 关系理解
    emotion_trend: str               # 情绪趋势
    world_state_context: str         # world_state.to_prompt()
    active_topics_context: str       # active_topics.to_prompt()


class PromptBuilder:
    """System Prompt 渲染。只做渲染，不知道变量来源。"""

    def __init__(self, prompt_manager, character):
        self.prompt_manager = prompt_manager
        self.character = character

    def build(self, ctx: PromptContext) -> str:
        """与 _build_system_prompt() 逐字符等价。"""
        if not ctx.identity:
            ctx.identity = self.character.to_identity()
        if not ctx.current_time:
            ctx.current_time = get_time_context()
        if not ctx.world_context:
            ctx.world_context = get_world_context()
        return self.prompt_manager.render("system", **dataclasses.asdict(ctx))
```

**设计要点**：
- Orchestrator 的 `_assemble_prompt_context()` 负责填充 11 个字段（含意图过滤结果）
- PromptBuilder **不知道变量来源** — 只渲染模板（Kimi #3）
- `render("system", **asdict(ctx))` 与现有 `render("system", identity=..., ...)` 逐参数等价
- `_dump_prompt()` 作为静态方法并入本模块

### 3.4 IdentityFlow（Orchestrator 子组件）

**归属决策（Kimi #1）**：IdentityFlow **不是独立层，是 Orchestrator 的子组件**。

理由：
- 它不拥有数据 —— 只编排 ProfileStore（Memory 域）和 profile_history 的确认流程
- 它是"协调者"而非"拥有者"
- 红线（Step 6a→7）自然落在 Orchestrator 内部，不跨模块

```python
class IdentityFlow:
    """身份三级确认流程。Orchestrator 子组件。V3 设计，行为不变。"""

    # 只依赖 ProfileStore + AsyncSessionLocal
    # 不持有 session / provider —— 不拥有任何跨域数据

    async def has_pending(self, platform, uid) -> bool: ...
    @staticmethod
    def looks_like_confirmation(message: str) -> bool: ...
    async def resolve_if_confirmed(self, platform, uid, message) -> None:
        """组合方法。⚠️ 红线：必须由 Orchestrator 在 Step 6a 同步 await。
        不提供异步/后台变体 —— 防止红线被破坏。"""
    async def get_confirmed_name(self, platform, uid) -> tuple[str|None, str]: ...
        # 被 Step 6c (IDENTITY_CHECK) 和 BackgroundTasks 复用
    async def create_pending(self, context, intent_name) -> None: ...
        # 被 BackgroundTasks.extract_profile 复用
```

**调用方清单**：

| 调用方 | 方法 | 位置 |
|--------|------|------|
| Orchestrator Step 6a | resolve_if_confirmed | 同步 await，红线内 |
| Orchestrator Step 6c | get_confirmed_name | IDENTITY_CHECK 分支 |
| BackgroundTasks | create_pending | 提取流程（原 _extract_profile_async） |

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
    """4 个后台任务。共享 session 引用（经 session_lock 访问）。"""

    def __init__(self, memory, relationship, provider): ...

    async def summarize(self, session) -> None:
        # 原 _summarize_async：LLM 摘要（不持锁 await）→ 加锁写 session.summary + 截断前 8 条
        # 锁规则见 3.2

    async def generate_timeline(self, context, summary) -> None: ...
    async def trigger_growth(self, platform, uid) -> None: ...
    async def extract_profile(self, context, raw_reply) -> None:
        # ⚠️ 参数是 raw reply（非 clean_reply）—— 保持

# 触发点仍在 Orchestrator：
# _create_background_task(BackgroundTasks().summarize(session))
```

---

## 四、行为一致性测试（安全网，Kimi #4）

### 4.1 测试设计

```python
# scripts/behavior_consistency_test.py（新增，非 pytest —— 属于拆分验证工具）

"""行为一致性测试：同一组输入，对比拆分前后 ChatResponse.content + DB 终态。

用法（每批拆分后运行）：
    python scripts/behavior_consistency_test.py --baseline out_before.json
    python scripts/behavior_consistency_test.py --compare out_after.json
"""
```

**流程**：

| 步骤 | 动作 |
|:--:|------|
| 1 | 拆分前：`DATABASE_URL=临时库` 启动，跑 20 条固定输入（覆盖 5 意图 + 身份确认 + 长消息），记录 `{input → reply, memory_updated}` + 8 表 checksum → `baseline.json` |
| 2 | 每批拆分后：同一临时库（清空重置），同一 20 条输入，记录 → `after.json` |
| 3 | 对比：`reply 完全一致` + `memory_updated 一致` + `8 表 checksum 一致` |

**输入集设计**（20 条，覆盖全部意图分支）：

```python
CONSISTENCY_INPUTS = [
    # GREETING
    ("t1", "你好"), ("t2", "晚安"),
    # IDENTITY_CHECK（需 pending 流程）
    ("t3", "我叫测试员"), ("t4", "对，就叫测试员"), ("t5", "我是谁"),
    # RECALL_PAST
    ("t6", "我们昨天聊了什么"),
    # DEEP_TALK
    ("t7", "我觉得最近压力很大，总是睡不好，白天也很累，不知道该怎么办"),
    # DAILY_CHAT
    ("t8", "今天下雨了"), ("t9", "吃了吗"), ("t10", "我出门了"),
    # 引用回复
    ("t11", "在干嘛"),
    # 长消息
    ("t12", "我想了很久，决定告诉你我喜欢画画，但最近有点想放弃了"),
    # 文学诱导
    ("t13", "月亮"), ("t14", "睡不着"),
    # 偏好提取
    ("t15", "我喜欢下雨天和猫咪"), ("t16", "你知道我喜欢什么吗"),
    # 重复意图
    ("t17", "在吗"), ("t18", "在干嘛"),
    # 身份变更
    ("t19", "把名字改成小月"), ("t20", "就叫小月"),
]
```

**DB checksum 实现**（8 表）：

```python
async def db_checksum() -> str:
    """对 8 张表逐行计算 SHA-256 摘要。"""
    tables = ["users","messages","memory_records","user_profiles",
              "profile_history","relationship_metrics",
              "relationship_timeline","relationship_memories"]
    for t in tables:
        rows = await session.execute(text(f"SELECT * FROM {t} ORDER BY id"))
        for row in rows:
            h.update(str(row).encode())
```

### 4.2 对比阈值

| 检查项 | 必须 |
|--------|:--:|
| reply 文本 | 100% 一致 |
| memory_updated 标记 | 100% 一致 |
| DB checksum | 100% 一致 |
| 允许差异（LLM 随机性） | 无 —— 20 条输入足够确定，若 LLM 输出随机导致不一致，重跑 1 次确认 |

> ⚠️ 注意：LLM 输出本身有随机性（temperature=0.7），行为一致性测试的 **reply 对比允许 ±1 次重跑确认**。真正的硬指标是 **DB checksum 100% 一致**（DB 状态由确定逻辑驱动，与 LLM 输出无关的部分必须一致）。

---

## 五、日志/观测性（Kimi 补充点）

### 5.1 contextvars 结构化日志（Phase A 后可选增强）

```python
# ai/context.py（新增，可选）
import contextvars

_current_turn = contextvars.ContextVar("turn_id", default="")

def get_turn_id() -> str:
    return _current_turn.get()

def set_turn_id(turn_id: str) -> None:
    _current_turn.set(turn_id)
```

```python
# Orchestrator.chat() Step 0：
import uuid
set_turn_id(f"{context.platform}:{context.platform_user_id}:{uuid.uuid4().hex[:8]}")
```

```python
# utils/logger.py 扩展 format（可选）：
# "[{time} | {extra[turn_id]}] ..."  —— 仅 loguru extra 字段，不改变日志级别
```

**收益**：拆分后调用链变长，`turn_id` 让每个模块的日志可串联。**约束**：不改变现有日志内容（只追加字段），OC 观察体系不受影响。

**实施时机**：Phase A 完成、核心拆分稳定后（可选，不阻塞 Stage 0 验收）。

---

## 六、迁移顺序

### Phase A — 第一批（零风险，纯搬移）

| 步骤 | 动作 | 验证 |
|:--:|------|------|
| A1 | 新建 `ai/intent.py`：搬 Intent/detect_intent/关键词（core.py 36-90） | 37 测试 + 一致性测试 |
| A2 | 新建 `ai/message_formatter.py`：搬 _format_user_message（547-570） | 37 测试 |
| A3 | 新建 `ai/prompt_builder.py`：搬 _build_system_prompt + _dump_prompt（618-725） | 37 测试 + 一致性测试 |
| A4 | core.py 改为 import 调用，删除原实现 | 37 测试 + 52 观察回归 |

**验收**：core.py 减少 ~190 行；测试零改动通过。

### Phase B — 第二批（中风险，有状态）

| 步骤 | 动作 | 验证 |
|:--:|------|------|
| B1 | 新建 `ai/session_manager.py`：搬 ConversationSession + 4 个会话方法 + session_lock | 37 测试 + 一致性测试 |
| B2 | 新建 `ai/identity.py`：搬 5 个身份方法，组合 resolve_if_confirmed | 37 测试 + 身份用例回归（"我叫小七"→确认→召回） |
| B3 | 新建 `ai/world_updater.py`：搬 5a/5b/5c 逻辑 | 37 测试 |

**验收**：core.py 减少 ~370 行；身份红线测试（pending→同一轮可见）必须通过。

### Phase C — 第三批（高风险，最后）

| 步骤 | 动作 | 验证 |
|:--:|------|------|
| C1 | 新建 `ai/background_tasks.py`：搬 4 个后台任务 + _create_background_task + session_lock 集成 | 37 测试 + 一致性测试 |
| C2 | core.py 瘦身为纯 Orchestrator（目标 ≤350 行） | 37 测试 |
| C3 | 完整回归：52 观察用例与 OC-3 数据对比 | 表达基线无差异 |

**验收**：core.py ≤ 350 行；`chat()` 方法体无超过 5 行的独立逻辑块。

---

## 七、红线检查表（每 Phase 完成后核对）

| # | 红线 | 验证方式 |
|---|------|---------|
| 1 | 37/37 测试通过，断言零改动 | pytest |
| 2 | 身份确认同轮可见 | 测试：pending 创建 → resolve → 同一轮 Prompt 含名字 |
| 3 | context_visible user/assistant 同值 | 单测断言 |
| 4 | LLM 失败返回 "……" | 现有 test_api_chat 覆盖 |
| 5 | Prompt 渲染结果与拆分前逐字符一致 | 快照测试（拆分前 dump 一次，拆分后对比） |
| 6 | system.yaml / memory / relationship 零改动 | git diff 仅 ai/ 下新增文件 |
| 7 | 行为一致性测试通过（DB checksum 100% 一致） | scripts/behavior_consistency_test.py |

---

## 八、不做的事

| 事项 | 原因 |
|------|------|
| 不引入 Provider 抽象基类 | Stage 0 只划边界，不重构 Provider |
| 不新增 retry/fallback | V4 后续阶段 |
| **不选并发策略 B/C** | B（消息队列）架构变化大；C（快照隔离）需改 session 不可变。Stage 0 选 A（Lock）最小变动 |
| 不拆 world_tracker.py (599 行) | 已独立，可后续评估 |
| 不改 PromptBuilder 的渲染输出 | 逐字符一致是验收标准 |
| 不动 memory/、relationship/、database/、prompt/ 任何文件 | 冻结规则 |
| 日志 contextvars 不阻塞拆分 | Phase A 后可选增强 |

---

## 九、完成定义（Stage 0 Done）

```
✅ core.py ≤ 350 行（Orchestrator 纯编排）
✅ 7 个新模块文件：intent / message_formatter / prompt_builder / session_manager / identity / world_updater / background_tasks
✅ 37/37 测试通过（断言零改动）
✅ 行为一致性测试通过（20 条输入，DB checksum 100% 一致）
✅ 52 观察用例与 OC-3 无差异
✅ Prompt 快照逐字符一致
✅ git diff 不触及 memory/ relationship/ prompt/templates/ database/
```
