# V4 Memory Evolution 详细设计

> Phase 4 | 版本：V4.0 Draft | 日期：2026-07-30

---

## 一、目标

V3 的 Memory 系统是"存储 → 召回 → 注入 Prompt"。Memory 数据被 LLM 参考，但 LLM 是否真正"用了"记忆，不可控。

**V4 Phase 4 目标**：Memory 不再仅注入 Prompt 文本，而是**驱动 CharacterState 和 SelfPersonality 变化**。

```
V3: Timeline → RelationshipMemory → Prompt 注入 → LLM 自由参考
V4: Timeline → 结构化影响 → CharacterState.mood 变化 → Prompt 注入 State → LLM 参考
```

**核心变化**：Memory 从"上下文填充"变成"行为驱动"。

---

## 二、Memory → State 影响链路

### 2.1 当前 V3 链路（保持不变）

```
用户消息 → MemoryExtractor → memory_records (LongMemory)
用户消息 → Summarizer → conversation_summary
用户消息 → RelationshipStore → relationship_timeline
```

### 2.2 V4 新增链路

```
Timeline 生成 → MemoryEvolution.analyze() → 结构化影响 → CharacterState 更新

结构化影响：
{
    "mood_delta": "concerned",     // 目标 mood
    "energy_delta": -0.05,         // energy 变化量
    "reason": "用户今天很累",       // 原因（用于日志）
    "ttl_hours": 24                // 影响持续时间（mood 回落）
}
```

### 2.3 影响规则

| Timeline 事件 | mood_delta | energy_delta | ttl_hours |
|-------------|-----------|-------------|:--:|
| "用户今天很累/辛苦" | concerned | -0.03 | 24 |
| "用户今天很开心/兴奋" | happy | -0.03 | 12 |
| "用户生病了" | concerned | -0.05 | 48 |
| "用户失眠/睡不着" | concerned | -0.05 | 24 |
| "用户分享了好事" | happy | -0.02 | 12 |
| 普通日常 | calm | -0.02 | 6 |

**设计决策**：
- `ttl_hours`：mood 不是永久的。`concerned` 在 24 小时后自然回落到 `calm`。
- `energy_delta` 为负：情绪波动消耗精力。
- 每次 Timeline 生成只影响一次 State，不累积。

---

## 三、Memory → SelfPersonality 影响链路

**Phase 4 后期**：Memory Consolidator 可以从对话中提取"用户发现绘梨衣喜欢 XX"，写入 SelfPersonality。

### 触发条件

| 条件 | 示例 |
|------|------|
| 用户明确注意到角色的偏好 | "绘梨衣你真的很喜欢安静" |
| 角色多次表现出相同行为 | 多次说"安静的地方很舒服" |
| Timeline 中有 3+ 条相同 topic | topic=安静 出现 3 次以上 |

### 写入方式

```python
# SelfPersonality 的 preferences 扩展
# 写入到 character/characters/eryi.yaml 的 self_personality.preferences
# 但标记为 "learned" 来源，与原始 YAML 定义区分
```

**设计约束**：
- SelfPersonality 的 YAML 修改是**追加**，不是覆盖
- 新学到的偏好标记为 `learned: true`，可以在审查时被识别
- 每次追加不超过 1 条，避免爆炸

---

## 四、MemoryEvolution 模块

### 4.1 接口

```python
# memory/evolution.py

class MemoryEvolution:
    """Memory → State/Self 影响引擎。"""

    async def on_timeline_generated(
        self,
        platform: str,
        platform_user_id: str,
        timeline_entry: dict,
        state_store: CharacterStateStore,
    ) -> dict:
        """Timeline 生成后，分析并驱动 State 变化。

        Returns:
            {"mood_changed": bool, "energy_changed": bool}
        """

    async def on_relationship_memory_added(
        self,
        platform: str,
        platform_user_id: str,
        memory_entry: dict,
        self_personality: SelfPersonality,
    ) -> dict:
        """RelationshipMemory 新增后，检查是否应扩展 SelfPersonality。

        Returns:
            {"preference_learned": str | None}
        """
```

### 4.2 在 ai/core.py 中的接入

```python
# 在 _generate_timeline_async() 中，Timeline 生成后调用

async def _generate_timeline_async(self, context, summary):
    result = await self.relationship.generate_timeline_if_needed(
        context.platform, context.platform_user_id, summary, self.provider,
    )
    if result:
        # V3: 触发关系理解提炼（现有）
        asyncio.create_task(self.memory.consolidate_timeline(...))

        # V4 Phase 4: 驱动 State 变化
        from memory.evolution import MemoryEvolution
        evolution = MemoryEvolution()
        asyncio.create_task(evolution.on_timeline_generated(
            context.platform, context.platform_user_id, result,
            self.state_store,
        ))
```

---

## 五、Timeline → State 的分析 Prompt

MemoryEvolution 使用独立的轻量 Prompt（不走主聊天 Prompt）：

```
ANALYSIS_PROMPT = """\
从以下共同经历中，分析角色的情绪应如何变化。

规则：
- 用户累/难过/生病 → 角色应该 concerned
- 用户开心/兴奋 → 角色应该 happy
- 普通日常 → 角色保持 calm
- 每次只输出一个 JSON

输入：
{timeline_summary}

输出：
{"mood":"concerned|happy|calm","energy_delta":-0.03,"reason":"一句话原因","ttl_hours":24}
"""
```

**设计决策**：
- 使用独立 Prompt，不污染主聊天 Prompt
- 输出是结构化 JSON，可直接解析
- 这个 LLM 调用是异步的，不阻塞回复

---

## 六、与现有 Memory 系统的关系

### 不修改的现有模块

| 模块 | 原因 |
|------|------|
| `memory/extractor.py` | Phase 4 不修改提取逻辑 |
| `memory/retriever.py` | Phase 4 不修改召回逻辑 |
| `memory/consolidator.py` | Phase 4 不修改提炼逻辑 |
| `memory/summarizer.py` | Phase 4 不修改摘要逻辑 |
| `memory/stores/` | Phase 4 不修改存储层 |

### 新增的模块

| 模块 | 说明 |
|------|------|
| `memory/evolution.py` | Memory → State/Self 影响引擎 |

**原则**：Phase 4 只做**加法**，不修改现有 Memory 代码。所有影响通过新增的 `evolution.py` 驱动。

---

## 七、数据流图

```
用户消息
  ↓
Summarizer → conversation_summary
  ↓
RelationshipStore.generate_timeline_if_needed()
  ↓
Timeline 生成（relationship_timeline 表新增一条）
  ↓
MemoryEvolution.on_timeline_generated()
  ├→ 调用 ANALYSIS_PROMPT（轻量 LLM）
  ├→ 解析结构化影响
  ├→ CharacterStateStore.update(mood, energy)
  └→ 日志记录影响原因
  ↓
下一轮对话时：
  CharacterState 注入 Prompt → LLM 看到 "情绪：concerned" → 回复更温柔
```

---

## 八、验收测试

```python
def test_timeline_drives_mood_change():
    """Timeline 生成"用户很累" → CharacterState.mood 变为 concerned。"""

def test_mood_falls_back_after_ttl():
    """concerned mood 在 24 小时后回落到 calm。"""

def test_energy_consumed_by_emotion():
    """mood 变化时 energy 应减少。"""

def test_evolution_does_not_modify_existing_memory():
    """MemoryEvolution 只影响 State，不修改 memory_records。"""

def test_evolution_prompt_is_separate():
    """MemoryEvolution 使用独立 Prompt，不影响主聊天 Prompt。"""
```

---

## 九、不做的事

| 事项 | 原因 |
|------|------|
| 不修改现有 Memory 提取/召回/提炼逻辑 | Phase 4 只做加法 |
| 不做 Memory 的自动遗忘 | 现有 decay_score 机制已够用 |
| 不做 SelfPersonality 的自动覆盖 | YAML 追加，标记为 learned |
| 不做多步推理（Memory → State → Self → State） | 避免循环依赖 |

---

## 十、文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `memory/evolution.py` | 新增 | Memory → State/Self 影响引擎 |
| `ai/core.py` | 修改 | `_generate_timeline_async()` 中调用 evolution |
| `state/store.py` | 修改 | 新增 mood 回落逻辑（ttl） |
| `tests/test_v4_memory_evolution.py` | 新增 | 测试用例 |
