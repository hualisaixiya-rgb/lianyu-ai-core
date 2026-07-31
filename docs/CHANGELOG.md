# 版本变化记录

> 回答"过去为什么这么改"。每次版本记录修改内容、原因、影响范围。

---

## Test Deploy

- test: verify auto deploy pipeline

---

## V3.8（2026-07-31）

**修改**：稳定化修复 — 5 项已知问题修复，不新增功能，不改变架构。

1. 合并 `relationship.touch()` 重复调用（`ai/core.py` 227-246 行，V3.5 遗留）
2. 清理死代码：删除 `PromptManager.build_system_prompt()`（从未被调用）+ 删除 `prompt/templates/memory.yaml`（从未被加载）
3. 9 处 `except Exception: pass` 添加 `logger.debug` 日志（`ai/core.py`），静默失败不再完全无声
4. 5 处 `asyncio.create_task` 添加 30s timeout 包裹（`_create_background_task` 辅助函数），防止后台任务无限等待
5. 扩展 `_can_extract_profile()` 标记词（`memory/extractor.py`），新增"我平时/我经常/我习惯/我每天/我最近在"等日常表达场景，修复 `user_profiles` 中 likes/dislikes 等字段无法在日常聊天中被提取的问题

**原因**：V3.7 表达层稳定后，需要清理已知技术债，为 V4 架构拆分做准备。

**影响**：`ai/core.py`、`memory/extractor.py`、`prompt/manager.py`、`prompt/templates/memory.yaml`（删除）

**测试**：32/32 通过

---

## V3.7（2026-07-28）

**修改**：表达层重建

压缩 Persona + 表达规则，从 39 行精简到 22 行。用 10 个日常聊天示例替代抽象公式和情绪场景分类。

**原因**：V3.5~V3.6.1 累积的"不要 X"规则形成反向 primer，LLM 在受限制词触发文学模式后更难抑制。改用正面示例让 LLM 学习正确模式。

**影响**：`prompt/templates/system.yaml`（唯一改动文件）

**测试**：32/32 通过

---

## V3.6.1（2026-07-28）

**修改**：基于 V3.5 前真实对话（7/12-13，150 条回复，平均 13 字）提取正向表达样本。恢复"复述+简单回应"关心模式。

**原因**：V3.6 规则抽象（"回复按 1→2→3"），LLM 不理解公式，中性日常场景无参照样本。V3.5 前真实数据证明绘梨衣不需要文学化。

**影响**：`prompt/templates/system.yaml`

**测试**：32/32 通过

---

## V3.6（2026-07-28）

**修改**：Prompt 表层重构。删除词汇黑名单（"不要使用：星星、月亮、风、阳光、云、花"），合并散落的"不编造"规则（7 处 → 1 处）。

**原因**：黑名单中提到的词反而激活 LLM 的文学联想网络。散落的规则间隔太远，LLM 注意力权重递减。

**影响**：`prompt/templates/system.yaml`（70 行 → 28 行）

**测试**：32/32 通过

---

## V3.5.4（2026-07-28）

**修改**：增加禁止虚构自身生活细节规则；限制文学比喻（删除"星星/月亮/风/阳光/云/花"黑名单，改用正面约束）；增加日常口语优先约束。

**原因**：V3.5.3 后仍出现"一碗热粥，配了腌萝卜"和"心里有颗小星星亮起来了"。

**影响**：`prompt/templates/system.yaml`

**测试**：32/32 通过

---

## V3.5.3（2026-07-28）

**修改**：在"温柔"后立即添加"温柔不靠写很多字。一个简单的回应也可表达关心。"；在 `eryi.yaml` speaking_style 中修改 `……` 描述为"自然停顿，不用于营造文学氛围"。

**原因**：中文 LLM 训练数据中"温柔+……+安静"组合映射到轻小说/言情文学原型。需要在"温柔"和"文学化"之间插入显式切断。

**影响**：`prompt/templates/system.yaml`、`character/characters/eryi.yaml`

**测试**：32/32 通过

---

## V3.5.2（2026-07-28）

**修改**：新增反幻觉规则 + 反例（"我能想象你坐在窗边，看着阳光慢慢落下"→ 正确 vs 错误）

**原因**：V3.5.1 关闭了 relationship_memory_context 注入，但 LLM 仍然产生场景脑补。

**影响**：`prompt/templates/system.yaml`

**测试**：32/32 通过

---

## V3.5.1（2026-07-28）

**修改**：(1) GREETING/IDENTITY_CHECK/DAILY_CHAT 意图关闭 relationship_memory_context + emotion_trend 注入；(2) 删除 retriever 的 `list_all` fallback；(3) header `【你逐渐理解到】` → `【关于这段关系】`

**原因**：`【你逐渐理解到】` + 3 条心理分析式 relationship_memory 在简单问候时也注入，导致 LLM 进入洞察/文学模式。

**影响**：`ai/core.py`、`memory/retriever.py`、`memory/stores/relationship_memory_store.py`

**测试**：32/32 通过

---

## V3.5（2026-07-18~28）

**修改**：(1) Memory Source 标记（extractor → manager → storage 透传）；(2) Summary/Timeline Prompt 修复（主语"你们"→"对方"）；(3) LLM timeout（60s）；(4) Timeline V3.5 cutoff 优先级；(5) emotion_trend 阈值放宽（3/3 → ≥2/3）

**原因**：Memory Audit 发现 source 硬编码、Timeline 产生"你们一起洗澡"式 AI 物理化污染、LLM API 无 timeout。

**影响**：`ai/core.py`、`memory/stores/sqlite_store.py`、`memory/stores/relationship_store.py`、`memory/retriever.py`、`memory/relationship_growth.py`、`ai/providers/openai_compatible.py`

**测试**：32/32 通过

---

## V3.1（2026-07-09）

**修改**：Relationship Growth V3.1 — Pattern Discovery + Memory Merge + Emotion Trend

**原因**：Timeline 积累到 5 条后触发关系模式发现，合并重复关系理解。

**影响**：`memory/relationship_growth.py`、`memory/stores/relationship_memory_store.py`

---

## V3（2026-07-08）

**修改**：Chat Experience V3 基线 — 六层 Memory 架构、Intent 检测系统、World State、Active Topics、Pending Identity、Timeline 机制、事实优先级（Profile > LongMemory > ChatHistory）

**影响**：`ai/core.py`、`memory/`（全模块重构）、`database/models/`（新增 profile + relationship + timeline 表）、`prompt/templates/system.yaml`

---

## V2（2026-07-07~08）

**修改**：Memory Engine V2 — 四层 Memory（Profile / Relationship / LongMemory / RecentContext）、Subject 概念、Profile 不可降级、事实优先级

**影响**：`memory/`（V1 重构为 V2）

---

## V1（2026-07-05~07）

**修改**：初始版本 — 单表 memory_records、基础 Profile、Telegram Bot、Chat CLI、Voice 模块

**影响**：全部模块

---

## 版本号规则

- `V3` — 架构版本（大版本）
- `V3.5` — Memory Pipeline 修复（中版本）
- `V3.5.1` — 子修复（小版本）
- `V3.7` — 表达层重建（中版本，跳过 3.6 因为 3.6.x 是过渡迭代）

- test: verify auto deploy pipeline
