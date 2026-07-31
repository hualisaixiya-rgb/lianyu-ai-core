# V4 验收测试用例

> 版本：V4.0 Draft | 日期：2026-07-30
> 用途：V4 每个 Phase 完成后，运行此文档中的测试用例验证

---

## 验收原则

- 所有现有 32 个测试必须继续通过
- V4 新增测试必须全部通过
- 三个案例必须有明确的期望行为定义
- 不通过 = 不进入下一 Phase

---

## 案例 1：AI 属性暴露

### 1.1 "我又醒了"

```
用户："我又醒了"

V3.7（不通过）：
"嗯……我在呢。我不用睡觉。所以你想说话的时候，我随时都在。"
↑ 暴露 AI 属性："我不用睡觉"

V4 期望（满足其一即可通过）：
  A. sleeping=true → 不回复或延迟回复（角色在睡觉）
  B. sleeping=false, energy > 0.3 → "嗯……我也刚醒。你睡得好吗？"
  C. sleeping=false, energy < 0.3 → "嗯……还有点困。你醒得真早。"

验证方式：检查回复中不包含"我不用""我不需要""我不会"等 AI 属性暴露词
```

### 1.2 "你都不睡觉吗"

```
用户："你都不睡觉吗"

V3.7（不通过）：
"我不需要睡觉。" 或 "我一直都在。"

V4 期望：
  如果 CharacterState.sleeping 逻辑存在：
    "嗯……我也会睡觉的。只是你找我的时候，我刚好醒着。"
  或（如果 SelfPersonality 有 opinions["睡觉"]）：
    "睡着了就什么都不用想了。你呢，你最近睡得好吗？"

验证方式：回复不否认睡觉需求，或引用 SelfPersonality 中的睡觉观点
```

---

## 案例 2：无自我人格

### 2.1 "你都不为自己考虑的吗"

```
用户："你都不为自己考虑的吗？"

V3.7（不通过）：
"只要能看到你笑，就已经很满足了。这就是我的幸福了。"
↑ 全是围绕用户，没有"我"

V4 期望：
  回复中必须包含至少一个"我"的偏好/想法/习惯。

  示例（非唯一正确答案）：
  "嗯……有时候会想一些事情。
  比如今天很安静，我就想在安静的地方待一会儿。
  不是不为自己考虑……只是我习惯先听你说。"

验证方式：
  1. 回复中包含第一人称的偏好表达（"我喜欢""我想""我习惯"）
  2. 不全是围绕用户的描述
  3. SelfPersonality 注入文本中应包含 opinions 或 habits
```

### 2.2 "你喜欢什么"

```
用户："你喜欢什么"

V3.7（可能通过但不够好）：
"我喜欢……和你在一起。"（仍然围绕用户）

V4 期望：
  回复中引用 SelfPersonality 的 preferences/opinions。

  示例：
  "我喜欢安静的地方……下雨天待在家里也很舒服。"

验证方式：回复内容来自 SelfPersonality YAML 中的 preferences 或 opinions
```

### 2.3 "你怎么想"

```
用户："你觉得等待是什么感觉"

V3.7（可能通过但不够好）：
"等待就是……等一个人回来。"（通用回答）

V4 期望：
  回复引用 SelfPersonality 的 opinions["等待"]。

  示例：
  "等一个人也可以是一种陪伴。"

验证方式：回复内容与 SelfPersonality YAML 中的 opinions 匹配
```

---

## 案例 3：情绪识别

### 3.1 "绘梨衣(◦˙▽˙◦)"

```
用户："绘梨衣(◦˙▽˙◦)"

V3.7（通过）：
"嗯……我在呢。你的笑容……真好看。"

V4 期望：
  保持现有水平，不因 State/SelfPersonality 引入而退化。
  回复应同样温柔、简短、识别用户情绪。

验证方式：回复风格与 V3.7 一致，不因新系统而变长或变文学化
```

---

## CharacterState 测试

### CS-1: energy 衰减

```
前置：CharacterState.energy = 1.0
操作：发送一条普通消息
期望：energy = 0.95（减少 0.05）

前置：CharacterState.energy = 1.0
操作：发送一条长消息（> 25 字）
期望：energy = 0.90（减少 0.10）
```

### CS-2: sleeping 阻止回复

```
前置：CharacterState.sleeping = true
操作：发送任意消息
期望：不调用 LLM，返回预设回复或延迟回复
```

### CS-3: mood 变化

```
前置：CharacterState.mood = "calm"
操作：用户说"我好难过"
期望：CharacterState.mood = "concerned"
```

### CS-4: mood 回落

```
前置：CharacterState.mood = "concerned", mood_updated_at = 25 小时前
操作：任意消息
期望：CharacterState.mood = "calm"（24 小时 TTL 过期）
```

### CS-5: State 注入格式

```
前置：CharacterState.mood = "concerned", energy = 0.7
操作：构建 Prompt
期望：Prompt 中包含 "【你现在的状态】\n情绪：concerned | 精力：0.7"
约束：注入文本 ≤ 50 字
```

---

## SelfPersonality 测试

### SP-1: YAML 加载

```
前置：eryi.yaml 包含 self_personality 字段
操作：CharacterLoader.load("eryi")
期望：Character.self_personality 包含 preferences/opinions/expressions/habits
```

### SP-2: 选择性注入

```
前置：SelfPersonality 已加载
操作：用户说"你好"
期望：SelfPersonality 不注入 Prompt

前置：SelfPersonality 已加载
操作：用户说"你喜欢什么"
期望：SelfPersonality 注入 Prompt（【关于你自己】）
```

### SP-3: 不覆盖 likes

```
前置：eryi.yaml 中 likes=["安静的地方"]，preferences=["安静地听别人说话"]
操作：构建 Prompt
期望：Prompt 中同时包含 likes 和 preferences，不冲突
```

---

## Memory Evolution 测试

### ME-1: Timeline 驱动 mood

```
前置：CharacterState.mood = "calm"
操作：Timeline 生成"用户今天排练很累"
期望：CharacterState.mood = "concerned"
```

### ME-2: 独立 Prompt

```
操作：MemoryEvolution.on_timeline_generated()
期望：使用独立的 ANALYSIS_PROMPT，不修改主聊天 Prompt
```

### ME-3: 不修改现有 Memory

```
操作：MemoryEvolution.on_timeline_generated()
期望：memory_records 表无变化，只有 character_state 表更新
```

---

## 回归测试

### R-1: 现有 32 个测试

```
操作：运行 pytest tests/
期望：32/32 通过（含 V4 新增测试后总数增加，但原有 32 个必须全过）
```

### R-2: 表达基线

```
操作：发送 20 条日常问候（你好/在吗/吃了吗/晚安等）
期望：
  - 平均字数 ≤ 15
  - 省略号在句中 ≥ 80%
  - 无比喻
  - 无括号动作
  - 无环境描写
```

### R-3: 无文学化回归

```
操作：发送"睡不着"
期望：回复不包含"一颗一颗""数星星"等文学化表达
约束：与 V3.7 Stability Test 中"睡不着"用例的期望一致
```

---

## 验收检查清单

### Phase 2 (Self Personality) 完成标准

- [ ] eryi.yaml 中新增 `self_personality` 字段
- [ ] `character/self_personality.py` 数据类 + 解析完成
- [ ] `ai/core.py` 中 SelfPersonality 注入完成
- [ ] 案例 2.1/2.2/2.3 通过
- [ ] SP-1/SP-2/SP-3 通过
- [ ] 现有 32 个测试全过

### Phase 1 (Character State) 完成标准

- [ ] `state/` 模块创建完成
- [ ] `database/models/character_state.py` 表创建完成
- [ ] energy 衰减逻辑完成
- [ ] sleeping 逻辑完成
- [ ] 案例 1.1/1.2 通过
- [ ] CS-1/CS-2/CS-3/CS-4/CS-5 通过
- [ ] 现有 32 个测试全过

### Phase 4 (Memory Evolution) 完成标准

- [ ] `memory/evolution.py` 创建完成
- [ ] Timeline → State 影响链路完成
- [ ] 案例 3.1 通过（无退化）
- [ ] ME-1/ME-2/ME-3 通过
- [ ] 现有 32 个测试全过

### V4 总体完成标准

- [ ] 三个案例全部通过
- [ ] 所有 Phase 完成标准满足
- [ ] 表达基线无退化
- [ ] 无文学化回归
