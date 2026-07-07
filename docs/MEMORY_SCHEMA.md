# Memory Engine V2 —— 数据结构设计

> 状态：设计阶段  
> 日期：2026-07-07  
> 原则：先定义清楚"存什么、属于谁、怎么读"，再写代码。

---

## 零、当前问题溯源

### 0.1 Bug 现场

```
用户问："你还记得我是谁吗？"
机器人答："记得。你是夏离萤。也是小橘。"
                 ↑ 正确         ↑ 错误
```

### 0.2 根因分析

```
数据库实际状态：
┌─────────────────────────────────────────────────┐
│ user_profiles                                   │
│   name="夏离萤"  nickname="小离"                 │
│                                                 │
│ memory_records                                  │
│   id=7:  姓名 → "用户叫夏离萤"    ← 身份信息     │
│   id=8:  活动 → "用户要去超市"     ← 事件         │
│   id=9:  昵称 → "用户叫小离"      ← 身份信息     │
│   ...                                           │
│   id=N:  宠物 → "看到一只橘猫叫小橘" ← 宠物事件   │
└─────────────────────────────────────────────────┘
```

**三层缺陷叠加：**

| 层 | 问题 | 后果 |
|----|------|------|
| **存储** | 身份 / 事件 / 宠物 全部混在 `memory_records` 一个表里 | 无法区分"这是关于用户本人的事实"还是"关于用户宠物的故事" |
| **提取** | Extractor 把 Profile 信息和 LongMemory 信息都提取到 memories[] | `memory_records` 里有大量与 Profile 重复的冗余数据 |
| **召回** | `search()` 无结果 → `list_all()` 倒出全部记忆 | "我是谁？"这个问题收到了关于猫、超市、昵称的全部记忆 |

**根本原因不是 search 算法弱，而是 Memory 没有"主语（Subject）"概念。**

"今天看到一只橘猫"——这句话的主语是 Cat，不是 User。  
但在当前的 flat key-value 结构中，这个区别不存在。  
所有记忆都被当成"关于用户的事实"注入 Prompt。  
LLM 合理地把"小橘"理解成了用户的另一个名字。

---

## 一、Memory 分类体系

```
┌──────────────────────────────────────────────────────────────────┐
│                      Memory Engine V2                            │
│                                                                  │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────┐  │
│  │ Profile  │  │ Relationship │  │ LongMemory │  │  Recent   │  │
│  │ 用户档案  │  │ 关系状态      │  │ 长期记忆    │  │  近期上下文 │  │
│  └──────────┘  └──────────────┘  └────────────┘  └───────────┘  │
│       ↑              ↑                ↑               ↑          │
│   永久身份         关系计数         带主语的事件      滚动窗口       │
│   唯一值           唯一记录         多条记录         自动淘汰       │
│   直接读           直接读          按需搜索         不存储为记忆    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、Profile（用户档案）

### 职责
存储用户的**永久身份信息**。每个字段只有一个值。  
不参与搜索。始终注入 System Prompt。

### 数据结构

```python
Profile:
    # ---- 身份 (Identity) ----
    name:      str | None   # 姓名。唯一值。如 "夏离萤"
    nickname:  str | None   # 昵称。唯一值。如 "小离"
    birthday:  str | None   # 生日。如 "2000-03-15"
    school:    str | None   # 学校
    major:     str | None   # 专业
    job:       str | None   # 工作

    # ---- 偏好 (Preferences) ----
    likes:     list[str]    # 喜欢。如 ["猫", "雨天", "拉面"]
    dislikes:  list[str]    # 不喜欢。如 ["吵闹", "炎热"]
```

### 规则

| 规则 | 说明 |
|------|------|
| 唯一性 | `name` 只有一个值。用户说"其实我叫XX"→ 覆盖，不是追加 |
| 不参与搜索 | "我是谁？"→ 直接读 `profile.name`，不调 search() |
| 常驻注入 | 每次对话都加载 Profile，放在 System Prompt 中 |
| 增量更新 | 只更新用户明确说出的字段。不推断，不猜测 |
| 不可降级 | Profile 信息不进入 LongMemory。不出现"用户叫夏离萤"这种 memory_record |

### 读取方式

```
用户："我是谁？"
  → ProfileStore.get() → name="夏离萤"
  → 直接回答。不搜索。

用户："我喜欢什么？"
  → ProfileStore.get() → likes=["猫", "雨天"]
  → 直接回答。不搜索。

用户："你还记得我的专业吗？"
  → ProfileStore.get() → major=None
  → "你还没告诉过我呢。"
```

---

## 三、Relationship（关系状态）

### 职责
记录用户与 AI 之间的关系状态。**每个用户一条记录。**  
不参与搜索。始终注入 System Prompt（非敏感字段）。

### 数据结构

```python
Relationship:
    # ---- 时间 ----
    first_chat_at:   datetime   # 第一次聊天的日期
    last_chat_at:    datetime   # 最后一次聊天的日期

    # ---- 计数 ----
    total_chats:     int        # 总对话轮数
    consecutive_days: int       # 连续聊天天数

    # ---- 关系 ----
    bond_level:      int        # 亲密度 1-10
                                 # 1-3: 陌生人
                                 # 4-6: 熟人
                                 # 7-8: 亲近
                                 # 9-10: 非常亲近

    # ---- 备注 ----
    milestones:      list[str]  # 关系里程碑
                                 # 如 ["第100次聊天", "连续7天聊天"]
```

### 规则

| 规则 | 说明 |
|------|------|
| 自动更新 | `last_chat_at` 每次对话自动更新。`bond_level` 可选自动增长 |
| 只读 | LLM 只读取 Relationship，不能修改 |
| 轻量注入 | 只注入关键信息："你们已经认识了 X 天，亲密度 6/10" |
| 不参与搜索 | Relationship 不是"记忆"，是"状态" |

### 读取方式

```
用户："我们认识多久了？"
  → RelationshipStore.get() → first_chat_at="2026-07-01"
  → 计算天数 → 回答。

用户：不直接问关系问题
  → 静默注入："你和这个用户已经聊了 15 天。"
  → LLM 可以根据亲密度调整语气。
```

---

## 四、LongMemory（长期记忆）

### 职责
存储关于用户**生活中的人、事、物**的记忆。  
每条记忆**必须带有明确的 Subject（主语）**。  
按需搜索，不全部注入。

### 数据结构

```python
LongMemory:
    id:          int          # 自增主键
    platform:    str          # 平台
    user_id:     str          # 用户 ID

    # ---- 核心字段 ----
    subject:     Subject      # 主语：这段记忆是关于谁的？
    category:    Category     # 类型：这是什么类型的记忆？

    content:     str          # 记忆内容（简洁的一句话）
    importance:  int          # 重要性 1-10

    # ---- 时间 ----
    occurred_at: str | None   # 事件发生时间（可为空）
    created_at:  datetime     # 记忆记录时间
```

### Subject（主语）枚举

**每条 LongMemory 必须声明它"关于谁"。**

| Subject | 含义 | 示例 |
|---------|------|------|
| `User` | 用户本人 | "用户今年大学毕业" |
| `Pet` | 宠物 | "用户养了一只橘猫叫小橘" |
| `Family` | 家人 | "用户妈妈最近身体不好" |
| `Friend` | 朋友 | "用户的好朋友小明要结婚了" |
| `School` | 学业 | "用户下周期末考试" |
| `Work` | 工作 | "用户最近在找新工作" |
| `Hobby` | 爱好 | "用户周末常去钓鱼" |
| `Health` | 健康 | "用户最近失眠" |
| `Other` | 无法归类 | 兜底 |

**关键约束：**
```
Subject=Pet 的记忆不影响 Profile。
Subject=Friend 的记忆不影响 Profile。
Subject=Family 的记忆不影响 Profile。
```

### Category（类型）枚举

| Category | 含义 | 判定标准 |
|----------|------|----------|
| `Fact` | 客观事实 | "用户24岁" "用户是程序员" |
| `Event` | 发生过的事 | "用户昨天去了医院" "用户上周去了东京" |
| `Preference` | 偏好/习惯 | "用户喜欢雨天" "用户习惯早起" |
| `Dream` | 梦想/愿望 | "用户想开一家咖啡店" |
| `Achievement` | 成就 | "用户通过了N1考试" |

### 规则

| 规则 | 说明 |
|------|------|
| **必须有主语** | 每条 LongMemory 声明 Subject。默认不推断为 User |
| **不存储身份** | 姓名/昵称/生日 → Profile。不进入 LongMemory |
| **不存储关系** | 第一次聊天/连续天数 → Relationship。不进入 LongMemory |
| **不存储近期对话** | 临时话题 → RecentContext。不进入 LongMemory |
| **按需召回** | 根据用户问题，只召回相关 Subject 的记忆 |

### 读取方式

```
用户："我是谁？"
  → 只读 Profile。
  → LongMemory 不参与。✅

用户："我的猫叫什么？"
  → Profile 不相关。
  → LongMemory.search("猫", subject=Pet)
  → 返回："用户养了一只橘猫叫小橘" ✅

用户："我妈妈怎么样了？"
  → LongMemory.search("妈妈", subject=Family)
  → 返回："用户妈妈最近身体不好" ✅

用户："最近有什么重要的事？"
  → LongMemory.search(query, all subjects)
  → 按 importance 排序，返回 top 5
```

---

## 五、RecentContext（近期上下文）

### 职责
最近 N 轮对话的内容。**临时，滚动淘汰。不进长期存储。**

### 数据结构

```
RecentContext:
    messages:    list[Message]   # 最近 16 条消息
    summary:     str             # 滚动摘要（超窗口消息的压缩）
```

### 规则

| 规则 | 说明 |
|------|------|
| 已在现有系统中 | `session.messages` + `session.summary`（summarizer.py） |
| 不需要新建 | 本次设计只明确职责，不新增代码 |
| 自动淘汰 | 超过 16 条的消息被摘要压缩后丢弃 |
| 不进入 LongMemory | 临时闲聊（"今天吃了什么"）不提取为长期记忆 |

---

## 六、对比：V1 vs V2

### V1（现状）

```
memory_records（一个表装所有）
┌──────┬────────┬──────────────────────┐
│ key  │ value  │        问题           │
├──────┼────────┼──────────────────────┤
│ 姓名 │ 用户叫夏离萤 │ ← 和 Profile 重复  │
│ 昵称 │ 用户叫小离   │ ← 和 Profile 重复  │
│ 偏好 │ 希望能陪着他  │ ← Subject 不明    │
│ 活动 │ 要去超市     │ ← 事件，应该淘汰    │
│ 宠物 │ 橘猫叫小橘   │ ← Subject=Pet     │
│      │              │   但系统不知道     │
└──────┴────────┴──────────────────────┘
         ↓ 用户问"我是谁？"
         ↓ search() → list_all() → 全部倒出
         ↓ LLM 看到：夏离萤 + 小离 + 小橘 + 超市...
         ↓ 回答："你是夏离萤。也是小橘。"
         ❌ 混乱
```

### V2（设计）

```
Profile                   LongMemory
┌──────────────┐         ┌─────────────────────────────────────┐
│ name: 夏离萤  │         │ Subject=Pet:  橘猫叫小橘              │
│ nickname: 小离│         │ Subject=User: 用户今年大学毕业         │
│ likes: [...] │         │ Subject=Family: 妈妈身体不好           │
└──────────────┘         │ Subject=Hobby: 周末钓鱼               │
      │                  └─────────────────────────────────────┘
      │                           │
      │  用户问"我是谁？"           │
      │  ────────────→            │  ← 不参与
      │  直接读取                  │
      │  ←────────────             │
      │                           │
      ↓                           │
  "你是夏离萤。"                    │
  ✅ 干净                          │
                                   │
      用户问"我的猫叫什么？"         │
      ───────────────────────────→│
                                   │  search("猫", subject=Pet)
      ←───────────────────────────│
                                   │
      "叫小橘。"                    │
      ✅ 精确
```

---

## 七、数据流

### 7.1 写入流（对话后）

```
用户消息 + AI 回复
        │
        ▼
┌─────────────────────────────────────┐
│         MemoryExtractor             │
│                                     │
│  提取三个维度的信息：                 │
│                                     │
│  ┌─ Profile ────────────────────┐  │
│  │ 姓名/昵称/生日/学校/喜好...    │  │
│  │ → ProfileStore.upsert()      │  │
│  └──────────────────────────────┘  │
│                                     │
│  ┌─ LongMemory ─────────────────┐  │
│  │ 每条带 Subject + Category     │  │
│  │ → MemoryStore.add()          │  │
│  └──────────────────────────────┘  │
│                                     │
│  ┌─ Relationship ───────────────┐  │
│  │ 自动更新（非 LLM 提取）        │  │
│  │ last_chat_at / total_chats    │  │
│  │ → RelationshipStore.touch()  │  │
│  └──────────────────────────────┘  │
└─────────────────────────────────────┘
```

### 7.2 读取流（对话前）

```
用户消息 "我是谁？"
        │
        ▼
┌─────────────────────────────────────┐
│         MemoryRetriever             │
│                                     │
│  1. Profile（常驻，不搜索）          │
│     ProfileStore.get()              │
│     → "姓名：夏离萤"                │
│                                     │
│  2. Relationship（常驻，不搜索）      │
│     RelationshipStore.get()          │
│     → "认识 15 天，亲密度 6"         │
│                                     │
│  3. LongMemory（按需搜索）            │
│     分析 query → 确定 target_subjects│
│     "我是谁？" → 不需要 LongMemory   │
│     "我的猫？" → target=[Pet]        │
│     "最近怎样" → target=all, top_k=5 │
│     → 格式化为 Prompt                │
└─────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────┐
│         System Prompt               │
│                                     │
│  [角色设定]                          │
│  [Profile] ← 常驻                   │
│  [Relationship] ← 常驻              │
│  [LongMemory] ← 按需               │
│  [世界状态]                          │
│  [当前时间]                          │
└─────────────────────────────────────┘
```

---

## 八、为什么 V2 比 V1 更合理

### 8.1 解决当前 Bug

| V1 问题 | V2 解决方案 |
|---------|------------|
| "小橘"被当作用户名 | Subject=Pet 的记���不会在"我是谁？"时被召回 |
| "明天去超市"长期保留 | 事件型记忆可设置过期，或被更高重要性的记忆淘汰 |
| 姓名同时存在 Profile 和 Memory 中 | Profile 是唯一身份来源，Memory 不存身份 |

### 8.2 扩展性

| 未来需求 | V1 做法 | V2 做法 |
|----------|---------|---------|
| 关系成长 | 无数据结构，需要新表 | Relationship 已定义，填充逻辑即可 |
| 情绪记忆 | 混在 memory_records | 新增 Subject=Emotion，不改结构 |
| 回忆录 | 从 memory_records 随机抽 | 按 Subject 分组生成，更有条理 |
| 主动回忆 | 无法区分重要性 | Subject + Category + importance 三维排序 |

### 8.3 代码组织

```
V1:
  memory/manager.py  ← 所有逻辑
  memory/stores/sqlite_store.py  ← 所有存储

V2:
  memory/extractor.py       ← 提取逻辑（独立）
  memory/retriever.py       ← 召回逻辑（独立）
  memory/stores/
    ├── profile_store.py    ← Profile CRUD
    ├── relationship_store.py ← Relationship CRUD
    └── sqlite_store.py     ← LongMemory CRUD（加 subject 字段）
```

每个 Store 职责单一，可独立替换。

---

## 九、暂不开发

| 功能 | 状态 |
|------|------|
| 主动回忆（Recall） | 暂不开发 |
| 情绪曲线（Emotion） | 暂不开发 |
| 回忆录（Diary） | 暂不开发 |
| 向量搜索 | 暂不开发，保留接口 |
| 记忆自动淘汰 | 暂不开发 |

**本次只夯实：Profile + Relationship + LongMemory(with Subject) + RecentContext 四层基础。**
