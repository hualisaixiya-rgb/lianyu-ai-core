# Memory Engine V2 —— 统一架构设计

> 原则：记得该记得的。不编造。不炫耀。  
> 日期：2026-07-07  
> 状态：设计阶段

---

## 零、当前问题诊断

### 0.1 五个泄漏点

```
用户说 "你好呀"
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│ 泄漏 1: Memory Retrieval 无选择                          │
│                                                         │
│ get_context(query="你好呀")                               │
│   → search("你好呀") → 无结果 → fallback: list_all()     │
│   → 倒出 5 条高重要性记忆（不管是否相关）                  │
│   → "用户叫夏离萤" "用户承诺每天回来" "用户看到猫猫云"...  │
│   → 全部注入 Prompt                                      │
│                                                         │
│ 泄漏 2: Relationship Timeline 无条件注入                  │
│                                                         │
│ get_timeline_context() → 加载昨天 Timeline               │
│   → "下午，你在操场排练。绘梨衣一直陪着你。"               │
│   → 用户只是说"你好呀"，不需要这段                        │
│                                                         │
│ 泄漏 3: 所有 Context 全部注入 System Prompt               │
│                                                         │
│ {relationship_context}  ← 总是注入                       │
│ {profile_context}       ← 总是注入（这个 OK）              │
│ {memory_context}        ← 总是注入                       │
│ {conversation_summary}  ← 总是注入                       │
│                                                         │
│ 泄漏 4: Memory Extractor 每轮触发                         │
│                                                         │
│ 每次对话 → asyncio.create_task(extract_and_store)        │
│ "你好呀" → "你好呀。" → 触发一次 LLM 提取调用             │
│                                                         │
│ 泄漏 5: 提取 Prompt 无过滤条件                            │
│                                                         │
│ MemoryExtractor 从"你好呀""你好呀。"中                      │
│ 提取 Profile + LongMemory                                 │
│ → 提取出"用户叫夏离萤""用户承诺每天回来"                    │
│ → 覆盖已有正确数据                                        │
└─────────────────────────────────────────────────────────┘
```

### 0.2 根因

不是"记忆不够"，而是"记忆没有门"。

- 没有入口过滤（什么值得记）
- 没有出口过滤（什么应该注入）
- 没有路由策略（这个问题应该查哪种记忆）

---

## 一、统一 Memory Manager

### 1.1 架构图

```
                            MemoryManager (统一入口)
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
         Extractor             Retriever            Stores
              │                    │                    │
    ┌─────────┼─────────┐    ┌────┼────┐      ┌───────┼───────┐
    │         │         │    │    │    │      │       │       │
  Filter   Extract   Route  Intent Profile Memory  Profile LongMemory Timeline
  (该不该记) (提取)  (分发)  (意图) Store  Store   Store    Store    Store
```

### 1.2 统一入口

```python
class MemoryManager:
    """所有 Memory 操作的唯一入口。其他模块禁止直接访问 Store。"""

    # ---- 写入 ----
    async def ingest(turn: Turn) -> IngestResult:
        """对话后调用。决定是否提取、提取什么、存到哪里。"""
        # 1. Filter: 这轮对话值得提取吗？
        # 2. Extract: 如果是，调用 LLM 提取
        # 3. Route: 分发到 Profile / LongMemory / Timeline

    # ---- 读取 ----
    async def retrieve(query: str, intent: Intent) -> RetrieveResult:
        """对话前调用。根据意图选择性地召回记忆。"""
        # 1. Intent: 用户想干什么？
        # 2. Route: 这个问题需要哪种记忆？
        # 3. Format: 格式化注入 Prompt

    # ---- 禁止 ----
    # ❌ Store 不允许被外部直接 import
    # ❌ Prompt 不允许直接拼接记忆字符串
    # ❌ Role system 不允许访问 Memory 数据
```

---

## 二、选择性注入

### 2.1 注入策略

| 用户意图 | 注入什么 | 不注入什么 |
|----------|---------|-----------|
| 普通聊天 "你好呀" | Profile（精简版：仅姓名） | LongMemory, Timeline, Summary |
| 身份确认 "记得我吗" | Profile（完整版） | Timeline, LongMemory |
| 回忆过去 "我们聊过什么" | Timeline（最近 3 天） | — |
| 事实询问 "我喜欢什么" | Profile + LongMemory (search) | Timeline |
| 深度聊天 "最近压力好大" | Profile + LongMemory (relevant) + Timeline(1天) | — |
| 情感表达 "好累" | Profile（精简） | 其他 |

### 2.2 Profile 注入分级

```
精简版（普通聊天）：
  关于对方，你知道：姓名=夏离萤

完整版（身份确认）：
  关于对方，你知道：
  - 姓名：夏离萤
  - 昵称：小离
  - 专业：微电子科学与工程

最小版（日常陪伴）：
  （不注入任何 Profile，让对话自然流动）
```

### 2.3 实现方式

```python
class SelectiveRetriever:
    """意图驱动的选择��召回。"""

    async def retrieve(self, query: str) -> InjectContext:
        intent = self._detect_intent(query)

        ctx = InjectContext()

        if intent == Intent.GREETING:
            ctx.profile = ProfileLevel.MINIMAL
            # 不注入 LongMemory、Timeline

        elif intent == Intent.IDENTITY_CHECK:
            ctx.profile = ProfileLevel.FULL
            # 不注入 LongMemory、Timeline

        elif intent == Intent.RECALL_PAST:
            ctx.timeline_days = 3
            ctx.profile = ProfileLevel.COMPACT

        elif intent == Intent.DEEP_TALK:
            ctx.profile = ProfileLevel.COMPACT
            ctx.long_memory = await self._search(query, limit=2)
            ctx.timeline_days = 1

        elif intent == Intent.DAILY_CHAT:
            ctx.profile = ProfileLevel.COMPACT
            ctx.long_memory = await self._search(query, limit=1)
            # 不注入 Timeline

        return ctx

    def _detect_intent(self, query: str) -> Intent:
        """纯规则，零 Token。"""
        if len(query) <= 3 and not any(kw in query for kw in IDENTITY_KEYWORDS):
            return Intent.GREETING
        if any(kw in query for kw in ['记得我吗', '我是谁', '我叫什么']):
            return Intent.IDENTITY_CHECK
        if any(kw in query for kw in ['以前', '昨天', '聊过', '我们说过']):
            return Intent.RECALL_PAST
        if len(query) > 20:
            return Intent.DEEP_TALK
        return Intent.DAILY_CHAT
```

---

## 三、选择性提取

### 3.1 入口过滤

```
用户消息 + AI 回复
        │
        ▼
┌──────────────────┐
│ Ingest Filter     │
│                   │
│ 检查：             │
│ 1. 包含新的事实？   │
│ 2. 用户明确陈述？   │
│ 3. 非寒暄/问候？   │
│                   │
│ "你好呀" → ❌ 跳过 │
│ "今天好累" → ❌ 跳过│
│ "我是学微电子的" → ✅ │
│ "我下周有比赛" → ✅  │
└──────────────────┘
```

### 3.2 过滤规则

```python
INGEST_RULES = [
    # 必须同时满足：
    # 1. 用户消息长度 > 8 字
    # 2. 包含事实性陈述
    # 3. 不是纯寒暄/问候/感叹

    # 跳过：
    (r"^(你好|嗨|早|晚安|再见|拜拜|嗯|好|哦|哈哈|……)+$", SKIP),
    (r"^[我在].{0,5}(?:好累|好困|好饿|好热|好冷|开心|难过|烦)[了呀]?$", SKIP),
    (r"^.{0,10}(?:呢|吗|吧|呀|啊|哦)$", SKIP),  # 纯语气

    # 可以提取：
    (r"(?:我是|我叫|我在|我学|我做|我喜欢|我不喜欢|我有|我家|我(?:下[周月]|明天|今天|准备|打算))", EXTRACT),
]
```

### 3.3 提取后分类路由

```
LLM 提取结果
    │
    ▼
┌──────────────────┐
│ Route             │
│                   │
│ Profile 字段      │ → ProfileStore.upsert()
│   name/nickname/  │
│   school/major/   │
│   job/birthday    │
│                   │
│ LongMemory 条目   │ → MemoryStore.add()
│   重要事件/事实    │   (带 Subject)
│                   │
│ 其余 → 丢弃       │
└──────────────────┘
```

---

## 四、Relationship 降为隐藏状态

### 4.1 当前问题

```
Timeline 作为回复内容注入 Prompt：
  "下午，你在操场排练。绘梨衣一直陪着你。"
  → 模型看到这段 → 觉得应该"延续这个故事"
  → 输出："我在这里等你回来，像昨天一样。"
  → 伪造了"等待"这个行为
```

### 4.2 修正

```
Relationship 只影响回复方式，不出现在回复内容中。

Metrics:
  bond_level=3 → 语气稍微温柔
  bond_level=7 → 语气更亲近
  consecutive_days=15 → 可以自然流露熟悉感

Timeline:
  不注入 Prompt（除非用户明确问"我们聊过什么"）

Promises:
  不注入 Prompt（除非用户主动提起"你答应过……"）

System Prompt 中：
  ❌ 删除 {relationship_context}（当前实现）
  ✅ 改为 {relationship_tone}（仅语气指导）
      "你和对方认识了一段时间。对方比较信任你。"
      一句话。不描述具体事件。
```

---

## 五、数据边界

### 5.1 什么能进 Memory

| 层级 | 存储内容 | 判断标准 |
|------|---------|---------|
| **Profile** | 用户明确陈述的身份事实 | "我是学微电子的" → ✅ |
| **LongMemory** | 重要人生事件、明确偏好 | "我下周有比赛" → ✅ |
| **Timeline** | 每日共同经历摘要 | 当天对话结束，LLM 生成一条 |

### 5.2 什么不能进 Memory

| 不能进 | 原因 | 示例 |
|--------|------|------|
| 寒暄问候 | 临时，无信息量 | "你好呀" |
| 情绪表达（无事实） | 临时状态，每天变 | "好累""好热" |
| 纯语气回应 | 无信息量 | "嗯""哈哈""真的吗" |
| AI 自己的回复 | 不提取 AI 的话 | "我在这里等你" |
| 推断的喜好 | 用户没说，不能猜 | "你喜欢橘子汽水" |
| 角色设定内容 | 不属于用户 | "绘梨衣喜欢草莓大福" |

### 5.3 记忆归属判断

```
这句话是：
  关于用户本人的身份？→ Profile
  关于用户生活的重要事件？→ LongMemory (带 Subject)
  关于"我们"的共同经历？→ Timeline (每天一条，LLM 生成)
  关于聊天中的临时状态？→ 不存储
  AI 自己说的话？→ 不存储
  推断/猜测的内容？→ 不存储
```

---

## 六、实施计划

### Phase 1: 止血（立即）

只改代码，不改数据库。

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增 Intent 检测 | `ai/core.py` 或 `memory/retriever.py` | 纯规则，零 Token |
| 选择性注入 | `ai/core.py` `_build_system_prompt()` | 根据 Intent 决定注入什么 |
| 提取前置过滤 | `memory/extractor.py` | 长度/内容检查，跳过寒暄 |
| Timeline 不注入 Prompt | `ai/core.py` | 移除 `{relationship_context}` |
| Relationship 改为语气指导 | `ai/core.py` `_build_system_prompt()` | 一句话："你们认识了一段时间。" |
| 精简 Profile 注入 | `memory/stores/profile_store.py` | 新增 `format_compact()` `format_minimal()` |

### Phase 2: 结构化（后续）

| 改动 | 说明 |
|------|------|
| 统一 MemoryManager 入口 | 禁止外部直接访问 Store |
| Intent 路由表 | 可配置的意图 → 注入策略映射 |

### Phase 3: 扩展（远期）

| 改动 | 说明 |
|------|------|
| Relationship 语气调制 | bond_level → 影响 System Prompt 中的语气指导 |
| LongMemory 过期机制 | 低重要性事件自动降权 |

### 暂不开发

- Memory Diary
- Memory Reflection
- Proactive Recall

---

## 七、判定标准

每一条可能进入 Memory 的数据，必须通过三个问题：

| # | 问题 | 示例 |
|---|------|------|
| 1 | **信息来源明确吗？** | 用户说"我叫夏离萤" → ✅。模型推断"你喜欢橘子汽水" → ❌ |
| 2 | **是否真实发生？** | 用户说"我今天去了医院" → ✅。AI 说"我们昨天一起看云" → ❌（除非有 Timeline 记录） |
| 3 | **是否会改善未来理解？** | 记住用户专业 → 未来聊学业时有用 ✅。记住"今天吃了面条" → 未来无用 ❌ |

**3 个问题全部 YES → 进入 Memory。任何一个 NO → 不存。**

---

## 八、最终目标

```
Phase 1 完成后，绘梨衣应该做到：

"你好呀" → "你好呀。"（不展示记忆）
"记得我吗" → "记得。你是夏离萤。"（只展示 Profile）
"你还记得我们聊过什么吗" → 展示 Timeline（如果用户问）
"我最近压力好大" → "怎么了？"（不展示记忆，先了解）

不编造场景。不炫耀记忆。不推断喜好。
记得该记得的。不多说一句不必要的话。
```
