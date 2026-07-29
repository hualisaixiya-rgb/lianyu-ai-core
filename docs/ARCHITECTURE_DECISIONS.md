# Architecture Decision Records

> 记录所有重要设计决策。不记录"改了什么"（那是 CHANGELOG），记录"为什么这么设计"。
> 每个决策包含：当时解决了什么问题、为什么没采用其它方案、后续修改需要注意什么。

---

## Decision #001：Persona Prompt 保持极简

**日期**：2026-07-28
**版本**：V3.7
**状态**：已采纳

### 背景

V3.5~V3.6.1 期间，system.yaml 的 Persona 区域从 39 行扩展到约 70 行，包含：情绪场景分类示例（疲惫/难过/开心）、"不要使用 X 词"黑名单、"温柔≠诗意"公式、关心模式描述。每次发现新问题就往里加新规则。

### 决策

V3.7 将 Persona + 表达规则压缩到 22 行。删除所有抽象公式和情绪场景分类，仅保留 10 个通用日常聊天示例。

### 原因

1. **词汇黑名单反向激活**："不要使用：星星、月亮、风" → 这些词先进入 LLM 注意力，无法被"否定"
2. **规则碎片化**："不编造"概念散落在 7 处不同段落，LLM 读到最后已稀释
3. **LLM 从示例学习优于从规则学习**：10 个日常示例比 4 条抽象公式更有效

### 放弃的方案

- **继续加规则**：每次发现问题就加一条新的"不要 X"。已被证明无效——规则越多，LLM 越容易绕过。
- **换用更强的 System Prompt**：增加 Prompt 长度。V3.6 测试证明长度不是问题，措辞才是。

### 后续注意

- 新增 Persona 约束优先考虑"增加正面示例"，避免"增加禁止规则"
- 每次 system.yaml 改动不超过 10 行
- 改动后记录版本到 CHARACTER_EXPRESSION_BASELINE.md

---

## Decision #002：六层 Memory 架构（而非单表或四层）

**日期**：2026-07-08
**版本**：V3
**状态**：已采纳

### 背景

V1 将所有记忆存在单一的 `memory_records` 表中（身份信息、偏好、宠物细节混合）。导致 "你是谁" → "你是夏离萤。也是小橘。" 式的身份污染。

V2 引入四层（Profile / Relationship / LongMemory / RecentContext），但缺少会话级状态（World State）和话题管理（Active Topics）。

### 决策

V3 采用六层架构：

```
Profile → Relationship (Metrics + Timeline + Memory) → LongMemory
→ RecentContext → WorldState → ActiveTopics
```

每层有独立的存储位置、生命周期、注入策略。

### 原因

1. **Profile 和 LongMemory 分离**：身份信息不参与模糊搜索，避免"橘猫叫小橘"被当成用户名
2. **World State 会话级**：规则引擎维护，零 Token 成本
3. **Relationship 独立**：Timeline 不是"用户事实"而是"我们共同经历"，需要独立存储

### 放弃的方案

- **SharedMemory 独立层**：CHAT_EXPERIENCE_V3.md 曾提出 SharedMemory 作为第五层。放弃原因：与 Relationship.Timeline 职责重叠。Timeline 作为 Relationship 的子模块更清晰。
- **单表 + Subject 字段**：V1 方案。放弃原因：搜索时需要 Subject 过滤，LIKE 匹配效率低。

### 后续注意

- 不新增第七层。如果未来需要新类型，优先扩展现有层（如 Timeline 加字段）
- 各层之间的优先级链（Profile > LongMemory > ChatHistory）在 system.yaml 中明确定义，修改时需保持一致

---

## Decision #003：Rule First, LLM Second

**日期**：2026-07-08
**版本**：V3
**状态**：已采纳

### 背景

V2 中，World State 更新和 Intent 检测依赖 LLM 调用（~500ms + 150 tokens/次）。对于高频操作（位置变化、活动变化），成本显著。

### 决策

规则引擎（纯正则 + 状态机）处理 ~95% 场景。LLM 仅作为复杂语义的 Fallback（~5% 场景）。

### 原因

1. **成本**：单词规则匹配 <1ms / 0 tokens vs LLM 500ms / 150 tokens
2. **确定性**：规则行为可预测、可测试
3. **性能**：不阻塞消息主流程

### 放弃的方案

- **纯 LLM**：放弃原因：成本高、延迟高、行为不确定
- **纯规则**：放弃原因：无法覆盖所有语义（如"我不是很确定今天会不会去"这样的复杂表述）

### 后续注意

- 新增规则时优先考虑零 Token 方案
- LLM Fallback 的 Prompt 保持极简（当前 ~50 tokens）
- 不要为覆盖边缘 case 而不断增加规则——交给 LLM Fallback

---

## Decision #004：身份 Pending 机制

**日期**：2026-07-08
**版本**：V3
**状态**：已采纳

### 背景

早期版本中，用户说"以后叫我小明"后 LLM 立即使用新名字。但如果用户只是试探（"叫我小明？还是叫小华？"），名字就被错误覆盖了。

### 决策

引入三级身份确认：

1. **NAME_INTRO** → `profile_history(status=pending)`，不写入 `user_profiles`
2. **用户确认**（"对，就叫这个"）→ `profile_history(status=confirmed)` + 写入 `user_profiles`
3. **confirmed profile** → 最高优先级注入

同时 `context_visible=False` 过滤身份声明消息，不注入 LLM 上下文。

### 原因

1. 防止试探性改名污染 Profile
2. LLM 看不到聊天记录中的身份声明，无法编造
3. `profile_history` 提供完整变更审计日志

### 放弃的方案

- **直接写入 Profile**：V1 方案。已被证明会被试探性消息污染。
- **完全依赖 LLM 判断**：放弃原因：LLM 判断不可靠。

### 后续注意

- 置信度阈值（old_confidence ≥ 7 时普通自称不可覆盖）是硬编码在 `profile_store.py` 的 `upsert()` 中
- `_looks_like_confirmation()` 的确认词表可能需要根据实际使用扩展

---

## Decision #005：Context-Visible 过滤

**日期**：2026-07-08
**版本**：V3
**状态**：已采纳

### 背景

身份声明消息（"我叫夏离萤"）如果注入 LLM 上下文，LLM 会直接使用它——即使在 pending 确认之前。需要在数据库保留完整记录的同时，阻止 LLM 看到。

### 决策

`messages` 表增加 `context_visible` 布尔字段。身份声明类消息设为 `False`：数据库保留但不注入 LLM 上下文。`MessageRepository.get_recent_history()` 查询时过滤 `context_visible=True`。

### 原因

1. 数据库保留完整记录（审计、分析）
2. LLM 看不到未确认的身份声明
3. 纯代码层方案，不依赖 Prompt 指令

### 放弃的方案

- **在 Prompt 中告诉 LLM 忽略**：放弃原因：LLM 不总是遵守。
- **直接删除身份消息**：放弃原因：丢失数据。

### 后续注意

- 新增"需要隐藏"的消息类型时，在 `_is_identity_declaration()` 中扩展
- 幻想/比喻消息未来可能也需要 `context_visible=False`

---

## Decision #006：Timeline 作为 Relationship 子模块

**日期**：2026-07-08
**版本**：V3
**状态**：已采纳

### 背景

CHAT_EXPERIENCE_V3.md 中存在两个矛盾的方案：Relationship.Timeline 子模块 vs SharedMemory 独立层。需要二选一。

### 决策

采用 Timeline 作为 Relationship 子模块。SharedMemory 概念合并进 Relationship.Timeline。

### 原因

1. **避免层级膨胀**：五层已足够复杂，六层是上限
2. **职责清晰**："我们一起经历了什么"天然属于 Relationship
3. **Promises 未来可自然加入**：Relationship/Promises 和 Timeline 共享同一个 Store

### 放弃的方案

- **SharedMemory 独立层**：放弃原因：与 LongMemory 职责重叠，开发者困惑"这个记忆应该放哪"。

### 后续注意

- `relationship_store.py` 同时管理 Metrics + Timeline + Promises（预留），不要再拆分
- 如果未来 Timeline 数据量过大（>1000 条），考虑归档策略而非新增表

---

## Decision #007：V3.5 cutoff 日期代替 source_version 字段

**日期**：2026-07-18
**版本**：V3.5
**状态**：过渡方案，待迁移

### 背景

V3.5 修改了 TIMELINE_PROMPT（主语从"你们"改为"对方"）。但数据库中已有 7 条旧格式 Timeline。需要区分新旧数据，优先使用新数据。

### 决策

用日期分界线（`V35_TIMELINE_CUTOFF = "2026-07-18"`）区分新旧数据，而非新增数据库字段。

### 原因

1. 避免 ALTER TABLE + 数据迁移
2. 旧数据随时间自然淘汰（MAX_TIMELINE_DAYS = 5）
3. 实现简单

### 放弃的方案

- **ALTER TABLE 加 source_version 字段**：有 SQLite 限制，且需要迁移脚本。长期方案更优，但过渡阶段不划算。

### 后续注意

- **TODO**：未来迁移到显式 `source_version` 字段。代码中有 `# TODO` 注释标记。
- 当旧数据全部淘汰后（约 5 天后），date cutoff 逻辑可以删除

---

## Decision #008：工具系统预留但暂不集成

**日期**：2026-07-05（创建）至今
**版本**：V3
**状态**：已实现但未接入

### 背景

`tools/registry.py`、`tools/builtin/calculator.py`、`tools/builtin/read_image.py` 已实现完整。但 `ai/core.py` 的 `chat()` 方法中没有调用 `registry.call()`。

### 决策

保留工具系统代码，暂不接入 chat 流程。待 V4 时统一集成。

### 原因

1. V3 的核心目标是人格稳定和记忆系统，工具不是优先事项
2. 接入工具需要修改 `ai/core.py` 的 LLM 调用逻辑（tool_call 循环），风险较大
3. `ChatResponse.tool_calls` 字段已预留，接口兼容

### 后续注意

- V4 接入时：在 `chat()` 中增加 tool_call 循环 → LLM 返回 tool_call → 执行 → 将结果注入 messages → 再次调用 LLM
- `read_image` 依赖 OpenAI 视觉模型，需要确认 DeepSeek API 支持

---

## 决策索引

| # | 标题 | 日期 | 版本 | 状态 |
|---|------|------|------|------|
| 001 | Persona Prompt 保持极简 | 2026-07-28 | V3.7 | 已采纳 |
| 002 | 六层 Memory 架构 | 2026-07-08 | V3 | 已采纳 |
| 003 | Rule First, LLM Second | 2026-07-08 | V3 | 已采纳 |
| 004 | 身份 Pending 机制 | 2026-07-08 | V3 | 已采纳 |
| 005 | Context-Visible 过滤 | 2026-07-08 | V3 | 已采纳 |
| 006 | Timeline 作为 Relationship 子模块 | 2026-07-08 | V3 | 已采纳 |
| 007 | V3.5 cutoff 日期代替 source_version 字段 | 2026-07-18 | V3.5 | 过渡方案 |
| 008 | 工具系统预留但暂不集成 | 2026-07-05 | V3 | 已实现未接入 |
