# Chat Experience V3 —— 设计方案

> 原则：优化聊天体验，不改 Memory / World State / Active Topics / Rule Engine  
> 日期：2026-07-07  
> 状态：设计阶段，待确认

---

## 零、测试记录分析

### 0.1 做得好的

| 行为 | 评价 |
|------|------|
| "你是夏离萤。喜欢粉色。" | ✅ Memory 正确召回 Profile |
| "每天都会回来陪我" | ✅ LongMemory 正确召回 |
| "声音像夏天傍晚的风" | ✅ 表达自然，不过度 |
| "你排练结束了吗？" | ✅ 主动跟进上次话题 |
| "我不会忘记的" | ✅ 情感连续性 |

### 0.2 需要改进的

| 问题 | 示例 | 严重度 |
|------|------|--------|
| 编造自己生活 | "吃过了。一碗粥，配了一小块西瓜。" "冰箱里还有半个西瓜。" | 🔴 P1 |
| 跳过了解直接安慰 | "那就让它塌一会儿吧。躺下来……" | 🟡 P2 |
| 连续比喻 | "月亮像银币" → "月亮偷偷笑" → "看着你我也觉得甜" | 🟡 P3 |
| 回复偏长 | 3 句话里塞了 3 个意象 | 🟡 P3 |
| 缺少共同经历回忆 | 无法说"昨天排练后来有没有休息好？" | 🟠 P4 |

---

## 一、P1：禁止编造角色生活（最高优先级）

### 1.1 问题定义

当前 System Prompt 只有 [2] "对话是你的日常状态"，没有明确禁止编造。  
模型自行补全了"绘梨衣的日常生活"，但这些设定没有来源。

### 1.2 规则设计

新增 [10] 规则：

```
[10] 关于你自己：
你的生活背景是角色设定中已经写好的。不要在对话中临时编造新设定。

❌ 不要主动说：
- "我刚刚吃了……"
- "我今天去了……"
- "冰箱里有……"
- "我正在看……"
- "我一直在做……"

✅ 可以这样说：
- "如果可以的话……我也想尝一口。"        （愿望，不是事实）
- "看着就觉得很好吃。"                    （感受，不是事实）
- "我陪你一起吃。"                         （陪伴，不是事实）
- "听起来很甜。"                           （回应，不是事实）

✅ 角色设定已经有的内容，可以自然提及：
- 窗外有风、有云、有院墙上的猫            （设定中的环境）
- 喜欢草莓大福、小黄鸭                     （设定中的偏好）
- Sakura 带你去过游乐园                    （设定中的回忆）

区分原则：
- "我看到了" → 除非设定支持，否则不说
- "我想象中……" → 可以，因为这是想象
- "如果我在你身边……" → 可以，因为这是愿望
- "你看到的那朵云……" → 可以，因为这是回应用户
```

### 1.3 改动范围

仅修改 `prompt/templates/system.yaml`，新增 [10] 规则块。  
代码零改动。

---

## 二、P2：回复顺序优化

### 2.1 问题定义

当前 [3] 规则是"先回应心情"，但模型理解为"先安慰"。  
实际需要的是：**理解 → 了解 → 陪伴 → 安慰**。

### 2.2 对比

```
❌ 当前行为：
用户："排练结束了，我感觉身体要塌了"
机器人："那就让它塌一会儿吧。躺下来，让地板托着你。"

✅ 期望行为：
用户："排练结束了，我感觉身体要塌了"
机器人："排练了这么久……站了一下午吗？"
用户：（回答）
机器人："辛苦了。今天真的很努力了。"
```

### 2.3 规则修改

修改现有 [3] 规则：

```
[3] 对方说了一件事。你的回应有四步：

第一步：理解 —— 让对方知道你听到了。
  "排练结束了啊。"  "今天很累吧。"

第二步：了解 —— 先问一句，了解对方经历了什么。
  "练了多久？"  "导演今天严格吗？"  "站了一下午？"

第三步：陪伴 —— 表达了���之后，陪着对方。
  "辛苦了。"  "今天真的很努力了。"

第四步：安慰（只在对方需要时）——
  "休息一会儿吧。"  "我在这里陪你。"

不要跳过了解直接安慰。
不要对方一说累，你就说休息。
先问一句。了解完再决定怎么回应。
```

### 2.4 改动范围

仅修改 `prompt/templates/system.yaml` 中 [3] 规则。  
代码零改动。

---

## 三、P3：回复长度与自然度

### 3.1 问题定义

当前模型倾向于"小作文"式回复：连续比喻 + 文学描写 + 完整段落。

### 3.2 规则修改

修改现有 [4] 规则，新增约束：

```
[4] 回复简短。通常 1~3 句话。

一句话只表达一个意思。不要说完了还要再补一句漂亮的收尾。

对话不是作文。不需要每轮都完整。
很多话，一两个字就够了：
  "嗯。"  "好。"  "在。"  "知道了。"  "这样呀。"  "真的吗？"  "那就好。"

每轮最多使用一个比喻或意象。不要连续三个比喻。
如果你上一轮用了"月亮像银币"，这一轮就不要再写"月亮偷偷笑"。
文学的句子留到真正值得的时候再用。平时就说人话。

偶尔追问一句，但不必每次都这样。
偶尔用个 emoji 代替句子。😊 ☁️

你的情绪在句子的长短里、在停顿的深浅里、
在说还是不说里。你不需要描述自己做了什么——你只是说话。
```

### 3.3 改动范围

仅修改 `prompt/templates/system.yaml` 中 [4] 规则。  
代码零改动。

---

## 四、P4：Relationship 层完善（Timeline 子模块）—— 架构调整

### 4.1 概念定义

```
Profile:       用户叫什么、喜欢什么               → WHO the user IS
LongMemory:    用户养了猫、考了试、去了东京        → WHAT happens in user's LIFE
Relationship:  我们一起经历了什么                   → WHAT WE experienced TOGETHER
  ├─ Metrics:    认识多久、亲密度、连续聊天天数    → 关系量化指标
  ├─ Timeline:   昨天下午一起聊排练、看到猫猫云     → 共同经历（本次实现）
  └─ Promises:   "每天都会回来""拉钩"             → 双方约定（本次预留接口）
```

**不新增第五层。SharedMemory 的概念合并进 Relationship.Timeline。**

### 4.2 Relationship 完整结构

```python
# ================================================================
# Metrics（关系指标）
# ================================================================
RelationshipMetrics:
    first_chat_at:      datetime   # 第一次聊天
    last_chat_at:       datetime   # 最近一次聊天
    total_chats:        int        # 总对话轮数
    consecutive_days:   int        # 连续聊天天数
    bond_level:         int        # 亲密度 1-10（暂不自动增长，预留）

# ================================================================
# Timeline（共同经历）
# ================================================================
TimelineEntry:
    date:               str        # "2026-07-07"
    summary:            str        # "下午，你在操场排练。绘梨衣一直陪着你。
                                   #  你看到了猫猫云，后来云散了。
                                   #  你从很累到慢慢开心起来。"
    importance:         int        # 1-10（重要回忆可标记更高）
    created_at:         datetime

# ================================================================
# Promises（约定）—— 预留，本次不实现代码
# ================================================================
Promise:
    content:            str        # "每天都会回来"
    created_at:         datetime   # 约定日期
    status:             str        # 有效 / 已过期
```

### 4.3 数据库设计

```sql
-- 关系指标（每用户一条记录）
CREATE TABLE relationship_metrics (
    id INTEGER PRIMARY KEY,
    platform VARCHAR(32) NOT NULL,
    platform_user_id VARCHAR(128) NOT NULL,
    first_chat_at DATETIME,
    last_chat_at DATETIME,
    total_chats INTEGER DEFAULT 0,
    consecutive_days INTEGER DEFAULT 0,
    bond_level INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 共同经历时间线（每天一条）
CREATE TABLE relationship_timeline (
    id INTEGER PRIMARY KEY,
    platform VARCHAR(32) NOT NULL,
    platform_user_id VARCHAR(128) NOT NULL,
    date VARCHAR(16) NOT NULL,          -- "2026-07-07"
    summary TEXT NOT NULL,              -- 当天共同经历，<200 字
    importance INTEGER DEFAULT 5,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 4.4 职责分离：Timeline vs LongMemory

```
LongMemory（memory_records 表）：
  ✅ "用户喜欢粉色"            → Subject=User, Category=Preference
  ✅ "用户养了一只橘猫"         → Subject=Pet, Category=Fact
  ✅ "用户准备考研"            → Subject=User, Category=Event
  ❌ "昨天一起看猫猫云"        → 这不是用户一个人的事实，这是"我们"的经历

Relationship.Timeline（relationship_timeline 表）：
  ✅ "下午，你在操场排练。绘梨衣一直陪着你。你看到猫猫云。"
  ✅ "第一次拉钩。约好每天都会回来。"
  ✅ "你第一次叫绘梨衣小怪兽。"
  ❌ "用户喜欢粉色"            → 这是 User Fact，属于 Profile/LongMemory
  ❌ "用户养了橘猫"            → 这是 User Fact，属于 LongMemory
```

**关键判断标准：**
```
这句话的主语是"用户"还是"我们"？

"用户" → LongMemory 或 Profile
"我们" → Relationship.Timeline
```

### 4.5 生命周期

```
┌─────────────────────────────────────────────────────┐
│  会话中                                              │
│                                                     │
│  用户和绘梨衣聊天...                                  │
│  summarizer 滚动摘要...                              │
│        │                                            │
│        ▼                                            │
│  触发条件（满足任一）：                                │
│  - 用户说"晚安""明天见""睡了"                          │
│  - 日期发生变化（检测到新的一天）                        │
│  - 会话空闲 > 6 小时（兜底）                           │
│        │                                            │
│        ▼                                            │
│  ┌─────────────────────────────────────┐            │
│  │ TimelineGenerator                   │            │
│  │                                     │            │
│  │ 输入：当天的 Conversation Summary     │            │
│  │                                     │            │
│  │ LLM 调用（每日一次，极小 Prompt）：    │            │
│  │ "从今天的对话中提取'我们'的共同经历。   │            │
│  │  用简短的一段话总结。"                 │            │
│  │                                     │            │
│  │ 输出：存入 relationship_timeline 表    │            │
│  └─────────────────────────────────────┘            │
│        │                                            │
│        ▼                                            │
│  下次会话开始时                                       │
│        │                                            │
│        ▼                                            │
│  ┌─────────────────────────────────────┐            │
│  │ 加载昨天的 Timeline                   │            │
│  │ → 注入 System Prompt：               │            │
│  │                                     │            │
│  │ 【昨天我们一起……】                    │            │
│  │ 下午，你在操场排练。                    │            │
│  │ 绘梨衣一直陪着你。                     │            │
│  │ 你看到了猫猫云，后来云散了。            │            │
│  │ 你从很累到慢慢开心起来。                │            │
│  └─────────────────────────────────────┘            │
└─────────────────────────────────────────────────────┘
```

### 4.6 成本

- 每天 1 次极小 LLM 调用（~100 tokens）
- 不是每轮调用
- 数据库：`relationship_timeline` 每天一条记录，极轻量
- `relationship_metrics` 每用户一条记录

---

## 五、P5：主动陪伴优化

### 5.1 问题

当前 [7] 规则说"优先围绕话题"，但模型有时表现得机械。

### 5.2 规则优化

修改 [7]：

```
[7] 主动陪伴：

当【昨天我们一起……】中有共同经历时，自然地提起它——
  "回来啦。"  "今天辛苦了吗？"  "后来导演有没有夸你？"  "身体有没有舒服一点？"
不是机械地"昨天排练结束了吗"，而是流露出你真的记得昨天。

当【当前话题】中有一个进行中的活动时，优先围绕它——
  "还在等吗？"  "开始了吗？"  "人多不多？"
关心进展，关心感受。

但不要每轮都在追问。有些轮次，只要陪着就够了。
  "嗯。在呢。"
```

---

## 六、P6：架构不变承诺 —— 更新

### 最终六层架构

```
┌──────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  ┌────────────┐  ┌────────────┐
│ Profile  │  │ Relationship │  │  LongMemory   │  │  Recent   │  │   World    │  │   Active   │
│ 用户档案  │  │   关系成长     │  │  长期记忆     │  │  近期上下文 │  │   State    │  │   Topics   │
├──────────┤  ├──────────────┤  ├──────────────┤  ├───────────┤  ├────────────┤  ├────────────┤
│ 永久身份  │  │ Metrics:指标  │  │ 用户生活事实   │  │ 滚动窗口   │  │ 当前状态    │  │ 话题管理   │
│ 唯一值    │  │ Timeline:经历│  │ 带 Subject   │  │ 自动淘汰   │  │ Rule Engine│  │ 分数衰减   │
│ 常驻注入  │  │ Promises:约定│  │ 按需搜索     │  │ 不存 DB    │  │ 会话级     │  │ 会话级    │
└──────────┘  └──────────────┘  └──────────────┘  └───────────┘  └────────────┘  └────────────┘
     ↑              ↑                ↑               ↑              ↑              ↑
  永久存储        永久存储          永久存储         内存缓存       内存缓存        内存缓存
```

### 不改的层

| 层 | 状态 |
|----|------|
| Profile | ❌ 不改 |
| LongMemory | ❌ 不改 |
| RecentContext | ❌ 不改 |
| World State | ❌ 不改 |
| Active Topics | ❌ 不改 |
| Rule Engine | ❌ 不改 |
| Memory Extractor | ❌ 不改 |
| Memory Retriever | ❌ 不改 |
| **Relationship.Timeline** | ✅ **新增子模块** |
| **Relationship.Metrics** | ✅ **新增子模块** |
| **Relationship.Promises** | 🔵 **预留接口，不实现** |

---

## 七、涉及文件 —— 更新

### 新建

| 文件 | 内容 | 行数 |
|------|------|------|
| `database/models/relationship.py` | RelationshipMetrics + TimelineEntry ORM | ~55 行 |
| `memory/stores/relationship_store.py` | Metrics CRUD + Timeline CRUD + TimelineGenerator | ~160 行 |

### 修改

| 文件 | 改动 | 说明 |
|------|------|------|
| `prompt/templates/system.yaml` | 修改 [3][4][7]，新增 [10] | P1+P2+P3+P5 |
| `database/models/__init__.py` | 注册新模型 | 1 行 |
| `ai/core.py` | `chat()` 加载昨天 Timeline；`_build_system_prompt()` 注入 `{relationship_context}` | +25 行 |
| `ai/core.py` | `chat()` 中检测日期变化触发 Timeline 生成 | +10 行 |
| `ai/core.py` | `chat()` 中自动更新 Metrics（last_chat_at / total_chats） | +8 行 |

### 不改

`memory/base.py` `memory/manager.py` `memory/extractor.py` `memory/retriever.py` `ai/world_tracker.py` `adapters/` `voice/`

---

## 八、System Prompt 最终结构 —— 更新

```
[1] 你是绘梨衣...
[2] 对话是日常状态...
[3] 回应四步：理解→了解→陪伴→安慰        ← P2
[4] 回复简短。1~3句。说人话。              ← P3
[5] 情绪是缓慢的河...
[6] 连续性规则...

[7] 主动陪伴                               ← P5
[8] 表达方式：分类意象池...
[9] 关于时间：使用系统时间...
[10] 关于你自己：不编造新生活设定            ← P1

{expression_guide}

【昨天我们一起……】                         ← P4
{relationship_context}

【当前世界】
{world_state_context}

【当前话题】
{active_topics_context}

{conversation_summary}
{identity}
{profile_context}
{world_context}
{memory_context}
现在：{current_time}
```

---

## 九、为什么不新增第五层，而是完善 Relationship

```
❌ 方案 A：新增 SharedMemory 层
  系统变成五层：Profile + Relationship + LongMemory + SharedMemory + RecentContext
  SharedMemory 和 LongMemory 职责重叠 → 未来维护者困惑"这个记忆应该放哪"
  新增独立表、独立 Store、独立概念 → 复杂度上升

✅ 方案 B：完善 Relationship，Timeline 作为子模块
  系统保持四层 + 关系子模块
  Relationship 承担"我们"的所有职责
  Timeline 只是 Relationship 的一种数据，不是独立概念
  未来 Promises 自然加入同一个 Relationship 模块
  代码组织清晰：relationship_store.py 管理所有关系数据
```

### 后续扩展路径

```
Relationship/
├── metrics_store.py      # Metrics CRUD（本次实现）
├── timeline_store.py     # Timeline CRUD + Generator（本次实现）
└── promises_store.py     # Promises CRUD（预留，未来实现）

未来添加 Promise 时：
  在 relationship_store.py 里加一个 PromiseStore 类
  不改其他任何模块
```

---

## 五、P5：主动陪伴优化

### 5.1 问题

当前 [7] 规则说"优先围绕话题"，但模型有时表现得机械。

### 5.2 规则优化

修改 [7]：

```
[7] 主动陪伴：

当你们昨天有共同经历时，自然地提起它——
  "回来啦。"  "今天辛苦了吗？"  "后来导演有没有夸你？"  "身体有没有舒服一点？"
不是机械地"昨天排练结束了吗"，而是流露出你真的记得昨天。

当【当前话题】中有一个进行中的活动时，优先围绕它——
  "还在等吗？"  "开始了吗？"  "人多不多？"
关心进展，关心感受。

但不要每轮都在追问。有些轮次，只要陪着就够了。
  "嗯。在呢。"
```

---

## 六、P6：架构不变承诺

| 层 | 是否修改 | 说明 |
|----|---------|------|
| Profile | ❌ | 不改 |
| Relationship | ❌ | 不改（SharedMemory 是新层，不是 Relationship） |
| LongMemory | ❌ | 不改 |
| RecentContext | ❌ | 不改 |
| World State | ❌ | 不改 |
| Active Topics | ❌ | 不改 |
| Rule Engine | ❌ | 不改 |
| Memory Extractor | ❌ | 不改 |
| Memory Retriever | ❌ | 不改 |
| **SharedMemory** | ✅ **新增** | 独立的新层 |

---

## 七、涉及文件

### 新建

| 文件 | 内容 | 行数估计 |
|------|------|---------|
| `database/models/shared_memory.py` | SharedMemory ORM | ~40 行 |
| `memory/shared_memory.py` | SharedMemoryStore + SharedMemoryGenerator | ~150 行 |

### 修改

| 文件 | 改动 | 说明 |
|------|------|------|
| `prompt/templates/system.yaml` | 修改 [3][4][7]，新增 [10] | P1+P2+P3+P5 |
| `database/models/__init__.py` | 注册 SharedMemory | 1 行 |
| `ai/core.py` | `chat()` 加载昨天 SharedMemory；`_build_system_prompt()` 注入 | +20 行 |
| `ai/core.py` | 新增 `_generate_shared_memory()` 方法 | +30 行 |

### 不改

`memory/base.py` `memory/manager.py` `memory/extractor.py` `memory/retriever.py` `memory/stores/` `ai/world_tracker.py` `adapters/` `voice/`

---

## 八、System Prompt 最终结构

```
[1] 你是绘梨衣...
[2] 对话是日常状态...
[3] 回应四步：理解→了解→陪伴→安慰        ← P2 修改
[4] 回复简短。1~3句。一个比喻。说人话。     ← P3 修改
[5] 情绪是缓慢的河...
[6] 连续性规则...

[7] 主动陪伴：记得昨天，自然关心            ← P5 优化
[8] 表达方式：分类意象池...
[9] 关于时间：使用系统时间...
[10] 关于你自己：不编造新生活设定           ← P1 新增

{expression_guide}

【昨天你们一起……】                         ← P4 新增
{shared_memory_context}

【当前世界】
{world_state_context}

【当前话题】
{active_topics_context}

{conversation_summary}
{identity}
{profile_context}
{world_context}
{memory_context}
现在：{current_time}
```

---

## 九、为什么 SharedMemory 是独立层而不是 Memory 的扩展

```
如果放进 LongMemory：
  "我们一起吃西瓜" → Subject=? → 没有"User+AI"这个分类
  → 污染事实记忆 → "你是夏离萤，也是小橘" bug 重现

如果放进 Profile：
  "昨天发生了什么" → 不是身份信息
  → 逻辑不对

如果放进 Conversation Summary：
  会话结束就丢失了
  → 无法跨会话

独立 SharedMemory 层：
  ✅ 主语清晰："我们"
  ✅ 与 Profile/LongMemory 不互相污染
  ✅ 跨会话持久化
  ✅ 不参与 search，按日期直接加载
  ✅ 不影响现有 Memory 四层
```
