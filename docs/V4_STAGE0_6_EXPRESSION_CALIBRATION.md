# V4 Stage 0.6 Expression Calibration（设计 v2 + 实现记录）

> 版本：v2（实现完成）| 日期：2026-08-10
> 基线：`v4-stage0.5-stable` (c39e55b) | 测试：83/83（62 原有零修改 + 21 新增）| checksum：ALL PASS
> 目标：Expression Layer 增加表达强度调节——从"像绘梨衣的台词"到"像绘梨衣平时聊天"
> 范围：仅 ai/expression.py + utils/response_renderer.py + expression 配置 + golden cases（+ 调用点传参）
> 禁止（遵守）：eryi.yaml 人格 / identity.py / memory / relationship / LLM 主 Prompt / 新增 Boundary Layer

---

## 〇、v2 变更说明（用户确认的三项调整）

| # | Draft 1.0 方案 | v2 确认调整 |
|---|------|------|
| 1 | CHAT_SPEC 18 字/1 行 | **25 字/2 行**（实验值，避免复杂日常场景过度压缩；最终参数以 8-08 真实归档校准） |
| 2 | 文学浓度关键词计数降级 | **三规则检测**（文学+情绪组合 / 抽象意象堆叠 / 高浓度承诺式），避免误伤正常表达 |
| 3 | 深情表达统一压缩 | **场景匹配**：普通输入+高浓度文学回复→降档；**用户高情绪输入→合理深情回复保留** |

---

## 一、当前 Expression Layer 工作流程分析

### 1.1 数据流（Stage 0.6 后）

```
AICore.chat() → raw reply（LLM 原始输出）
    ↓
render_for_user(reply, user_msg)  [utils/response_renderer.py]
    ↓
apply_expression(reply, infer_spec(reply, user_msg))
    ├─ ① normalize_ellipsis_prefix(text, max_prefix)  ← 按规格（chat=0 / 其他=1）
    ├─ ② dedup_adjacent_sentences
    ├─ ③ collapse_lines(spec.max_lines)
    └─ ④ truncate_to_max(spec.max_chars)
    ↓
send（Telegram bot.py / API chat.py）
```

### 1.2 规格推断（Stage 0.6 后）

```
infer_spec(text, user_msg=None)
  ├─ user_msg 高情绪（难过/哭/想你了…）→ 关键词档（不降档）—— 优先级最高
  ├─ user_msg 轻量问候（你好/哈咯/在吗…）→ CHAT_SPEC
  └─ 否则 → 关键词档（deep > emotion > daily）
       └─ 落 deep 且文学强度高 → 降 EMOTION_SPEC
```

### 1.3 结构性缺陷（Stage 0.6 修复目标）

| # | Stage 0.5 缺陷 | Stage 0.6 修复 |
|---|------|------|
| D1 | infer_spec 只看回复文本，无用户消息上下文 | infer_spec 增加 user_msg 参数（问候/高情绪场景判定） |
| D2 | 规格只约束上限，短而浓的文学表达零处理 | 文学强度检测 → deep 降档收紧（呈现峰值衰减） |
| D3 | 省略号只合并不删除（风格特征） | 省略号档位化：chat 删句首/孤立行，daily 限 1 次，emotion/deep 保留（情绪工具） |

---

## 二、问题对应的代码位置（Stage 0.6 改动清单）

| 文件 | 改动 |
|------|------|
| [ai/expression.py](ai/expression.py) | 新增 CHAT_SPEC(25/2)、USER_EMOTION_KEYWORDS、LITERARY_KEYWORDS、问候/高情绪/文学强度检测、infer_spec(user_msg)、normalize_ellipsis_prefix(max_prefix) |
| [utils/response_renderer.py](utils/response_renderer.py) | render_for_user(text, user_msg=None) |
| [adapters/telegram/bot.py](adapters/telegram/bot.py) | 传 update.message.text 作为 user_msg（1 行） |
| [api/v1/chat.py](api/v1/chat.py) | 传 req.message 作为 user_msg（1 行） |
| [tests/golden_cases/expression/cases.json](tests/golden_cases/expression/cases.json) | +3 无上下文 golden（文学降档/不误伤） |
| [tests/golden_cases/expression/cases_context.json](tests/golden_cases/expression/cases_context.json) | 新增：7 带 user_msg 的 golden |
| [tests/test_expression.py](tests/test_expression.py) | +14 单测（仅新增，零修改既有） |

零改动：render_for_storage / core.py / prompt / memory / relationship / database（checksum 保持）

---

## 三、修改设计（v2 最终版）

### 3.1 规格

| 档 | max_chars | max_lines | 句首省略号 | 场景 |
|------|:--:|:--:|:--:|------|
| **chat（新增）** | 25（实验值） | 2 | **删除**（含孤立省略号行） | 打招呼/闲聊/简单互动 |
| daily | 30 | 2 | 限 1 次（堆叠压缩） | 日常 |
| emotion | 40 | 3 | 保留 | 情绪承接 |
| deep | 60 | 4 | 保留 | 深度对话 |
| （降档） | deep 落档 + 文学强度 → emotion 上限 | | | 高浓度文学堆叠 |

CHAT_SPEC 25 字/2 行为实验值（设计确认指定 25-35 范围）；最终参数以 8-08 真实归档校准。

### 3.2 场景判定（新增，纯规则）

```python
is_greeting(user_msg)      # 问候模式：你好/哈咯/嗨/在吗/早安…+ "早[呀啊]?$"精确匹配
is_high_emotion(user_msg)  # 高情绪词表：难过/哭/害怕/孤独/想你了/好累/失眠…（35 词）
```

优先级：**高情绪 > 问候 > 关键词**（混合消息"哈咯啊我好难过"→ 保护深情表达）。

### 3.3 文学强度检测（三规则，任一命中）

| 规则 | 模式 | 示例 |
|------|------|------|
| 1. 文学词+情绪词组合 | LITERARY_KEYWORDS(16词) ∩ EMOTION_KEYWORDS | "我好难过……你是我的星辰。" |
| 2. 抽象意象堆叠 | "是我(的)?{意象}" 排比 ≥2；或同句意象间距 ≤15 字 | "你是我的星辰，是我的港湾，是我的归处。" |
| 3. 高浓度承诺式 | 永远/一辈子/此生/无论{0,6}…{0,8} 等/陪/守/留/爱… | "无论多远，我都会陪着你。" |

**防误伤设计**（生产数据驱动）：
- "星星/风/光"等日常中性词**不在**意象表——"那我是星星。每晚都在。"（话题相关）不触发
- "一直"**不在**承诺触发词——"我会一直陪着你"（轻度）不降档
- daily 落档的短文学/承诺表达**不降档**——"你是我的星辰。"原样保留（"问题不是不能出现"）

### 3.4 降档策略（表达强度匹配场景）

| 用户输入 | assistant 回复 | 处理 |
|------|------|------|
| 轻量问候（哈咯啊） | 深情/高浓度 | chat 档（25字/2行 + 删句首省略号）压缩呈现 |
| 高情绪（我好难过） | 合理深情 | **保留**（不降档，含文学浓度） |
| 普通（嗯/好的） | 高浓度文学（落 deep） | 降 emotion 档截断（收紧峰值） |
| 普通 | 短文学/承诺（落 daily） | 不降档（不误伤） |

### 3.5 诚实边界（与 Draft 1.0 一致）

- 渲染层控制**呈现**峰值（截断/删省略号），不阻止 LLM **生成**高浓度文本
- "频率过高"的根治在生成端（prompt，被禁止）——留待 8-08 数据回放后独立决策
- 不删除不超限的文学表达；不新增 Boundary Layer

---

## 四、测试（实施结果）

| 组 | 数量 | 结果 |
|------|:--:|:--:|
| 既有测试（Stage 0.5 + 全项目） | 62 | ✅ 零修改通过 |
| golden 无上下文新增（cases.json） | 3 | ✅ |
| golden 带上下文新增（cases_context.json） | 7 | ✅ |
| 单测新增（infer/文学检测/省略号档位/场景判定） | 14 | ✅ |
| **合计** | **83** | ✅ 全过 |
| behavior checksum（8 表） | — | ✅ ALL PASS（baseline.json meta 更新，checksum 未变） |

### golden 新增案例摘要

- `chat_greeting_compressed`：哈咯啊 → 深情回复压缩到 25 字/2 行
- `chat_ellipsis_removed`：……嗯，你好。→ 嗯，你好。（chat 档删句首省略号）
- `chat_sole_ellipsis_line_deleted`：……\n在的。→ 在的。
- `user_high_emotion_deep_preserved`：我好难过 → 深情回复完整保留
- `user_high_emotion_precedes_greeting`：哈咯啊我好难过 → 高情绪优先
- `normal_input_literary_downgrade_truncate`：普通输入 + 承诺式/意象堆叠 → 降档截断
- `literary_downgrade_truncate` / `literary_short_preserved` / `literary_commitment_daily_preserved`：降档与不误伤边界

---

## 五、待办与校准

1. **参数校准（必须）**：同步 8-08 真实归档 → 用真实样本校准 CHAT_SPEC（25 字是实验值）与文学词表
2. **观察指标**：spec 分布（chat/daily/emotion/deep 占比）+ 文学降档命中率记日志（48h 观察期）
3. 若 8-08 数据证明文学频率问题持续 → 生成端（prompt）修改需另行决策（解除冻结后）
4. 本设计 v2 提交后打 tag `v4-stage0.6-stable`（待发布确认）
