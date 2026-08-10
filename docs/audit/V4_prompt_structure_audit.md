# V4 Prompt 结构审查报告（Phase 1 回退后）

> 日期：2026-08-11 | 版本：v4-stage0.7 candidate + Phase 1（未 commit）
> 性质：只读结构审查。本会话修改仅 eryi.yaml（Phase 1 恢复，+5 行）；代码/system.yaml 零修改

---

## 1. 当前状态确认

**eryi.yaml 已恢复 Phase 1**（git diff 与原 Phase 1 一致，+5 行）：
- 回复必须回应用户刚刚说的内容本身，而不是寒暄
- 禁止用固定寒暄（如"晚上好""这么晚了还没睡"）覆盖对用户内容的回应
- 对方表达情绪时（累、难过、害怕、开心、生气），必须先回应那个情绪本身

## 2. 最终发送给 DeepSeek 的 Prompt 结构（实测 dump，1392 字符）

```
[0] system_prompt（最终消息首条）：
    │
    ├─ 1. [0] 信息来源优先级（已确认/长期记忆/聊天记录层级）
    │      + 身份变更规则 + 称呼语义 + 身体状态建议 + 比喻想象 + 存在感
    │
    ├─ 2. 你是绘梨衣。安静。真诚。温柔。          ← system.yaml 模板硬编码
    ├─ 3. ……是自然停顿。                          ← system.yaml 模板硬编码
    ├─ 4. 日常聊天示例（10 条）：
    │      "你好" → "你好。"
    │      "我好累" → "辛苦了……休息一下吧。"      ← system.yaml 模板硬编码
    │      "晚安" → "晚安……好梦。"（无深夜/时间类示例）
    │
    ├─ 5. 你不是现实中的人。不编造。不描述。…
    │
    ├─ 6. {identity} 实际注入内容（仅 3 行）：
    │      你是绘梨衣。
    │      安静、表达克制、语气轻柔。             ← personality 首行
    │      句子短。常只说一两个词。               ← speaking_style 首行（唯一注入的一行）
    │
    └─ 7. 现在：2026年8月10日 星期一 夏季 深夜 23:59  ← {current_time}，模板末行

[1] wrapped system（聊天记录参考提示，core.py 包装）
[2] user: 今天好累
```

## 3. 核心发现：eryi.yaml 注入严重丢失（代码层问题）

[character/loader.py:88-101](character/loader.py#L88-L101) `to_identity()`：

```python
if self.speaking_style:
    style_lines = self.speaking_style.strip().split("\n")
    for sl in style_lines:
        s = sl.strip()
        if not s:
            continue
        if any(kw in s for kw in ["这是你的说话方式", "不是你当前", "重点是", "不是描述自己"]):
            continue
        if len(s) > 50:
            s = s[:50]          # ← 行超过 50 字符被截断
        lines.append(f"{s.rstrip('。')}。")
        break                    # ← 只取第一条有效行
```

**后果（eryi.yaml speaking_style 15 行 → 实际注入 1 行）：**

| speaking_style 内容 | 注入状态 |
|---------------------|---------|
| 句子短。常只说一两个词。 | ✅ 注入（首行，50 字符内） |
| 停顿用"……"，不用于营造文学氛围 | ❌ **未注入**（break） |
| 语气轻柔。不主动推进话题 | ❌ 未注入 |
| 重点是：你说话的对象是对方。你回应的是对方实际说出的内容。 | ❌ **未注入**（且含"重点是"关键词被显式跳过） |
| 不要描述风景。不要创造画面。不要写故事。 | ❌ **未注入**（反文学化核心指令！） |
| **V4 Phase 1 Calibration 3 条指令** | ❌ **未注入**（在 5 行之后） |

## 4. 三轮实验结论的修正

| 实验结论 | 原解释 | 修正后解释 |
|----------|--------|-----------|
| Phase 1 模板复读 5→0 | Phase 1 指令生效 | **指令从未进入 prompt**——是采样随机性（temp 0.7） |
| Phase 1b 寒暄反弹 5→9 | 负面示例锚点/时间支配 | 同上，纯随机波动 |
| 情绪跟随三轮全 0/3 | 指令写法无效 | **指令根本没到模型**——结论需重做 |
| 8-08 文学化漂移（审计） | LLM 未遵守反文学化指令 | **反文学化指令从未注入**——prompt 从未约束过文学化 |

## 5. 当前问题定位（修正候选机制）

实际生效的说话风格约束只有：
1. system.yaml 硬编码："你是绘梨衣。安静。真诚。温柔。""……是自然停顿。" + 10 条日常示例
2. identity 3 行："安静、表达克制、语气轻柔。""句子短。常只说一两个词。"

而 `current_time`（"深夜 23:59"）位于 **system prompt 最末行**（recency 高注意力位），紧邻用户消息之前：

```
…句子短。常只说一两个词。
现在：2026年8月10日 星期一 夏季 深夜 23:59
──────────────────────────────────────────
user: 今天好累
→ 模型：睡不着吗？/ 这么晚了还没睡
```

**候选机制（需最小实验验证）：`current_time` 处于 prompt 末尾高注意力位 + 深夜时段 → LLM 将任意输入归入深夜场景。** 但注意：与"speaking_style 丢失"相比，时间支配可能是次因——真正的问题首先是**说话风格指令层缺失**。

## 6. 决策请求（未做任何修改）

问题分层：
- **A. 代码层（loader.py）**：`break` 只取 speaking_style 首行 + 50 字符截断 + "重点是"等关键词被显式跳过 → 修复方式：去掉 break、提高/去除截断、调整跳过关键词（属"修改代码"，当前被禁止）
- **B. 模板层（system.yaml）**：current_time 在末行（高注意力）→ 弱化时间或移动位置（属"修改 system.yaml"，当前被禁止）
- **C. eryi.yaml**：已恢复到 Phase 1——在 loader 修复前，任何 eryi.yaml 增补都不会到达模型

**建议优先级**：先修复 A（loader 注入丢失是确定性 bug），再重跑 Phase 0 基线对比；B 作为第二步最小实验（单变量）。两个都需解除对应约束。

## 7. 数据

- 实测 prompt dump：本报告 §2（完整 1392 字符）
- 注入逻辑：[character/loader.py:73-103](character/loader.py#L73-L103)
- 模板顺序：[prompt/templates/system.yaml:78-99](prompt/templates/system.yaml#L78-L99)
- 本会话 git 变更：仅 `character/characters/eryi.yaml`（+5 行 Phase 1，未 commit）
