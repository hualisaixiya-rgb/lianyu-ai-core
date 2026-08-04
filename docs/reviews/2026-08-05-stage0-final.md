# V4 Stage 0 最终架构报告（C3 验收）

> 日期：2026-08-05 | 基线：`v3.8.1-stable` → Stage 0 完成
> 类型：里程碑验收 | 性质：只验证，不修改业务逻辑

---

## 一、验收结果总览

| 验证项 | 结果 |
|--------|:--:|
| `pytest -x` | ✅ **37/37 passed** |
| `behavior_consistency_test.py` | ✅ **ALL PASS**（8 表 checksum + 12 断言 + metadata） |
| 52 Observation Regression（真实 LLM） | ✅ **52/52 通过，红线全零** |
| IdentityFlow Step 6a→7 红线 | ✅ 代码顺序 + Case 2 同轮可见 |
| BackgroundTasks session._lock | ✅ 临界区正确 + 不跨 await |

---

## 二、结构拆分成果

### 2.1 拆分前后对比

```
V3.8.1:  ai/core.py 1134 行（上帝对象，全部逻辑内聚）
                ↓
Stage 0:  ai/ 目录 8 个模块 + world_tracker，core.py 579 行
```

| 模块 | 行数 | 职责 | 阶段 |
|------|:--:|------|:--:|
| ai/core.py | 579 | Orchestrator（纯编排） | -49% |
| ai/intent.py | 61 | 意图检测（纯规则） | A1 |
| ai/message_formatter.py | 35 | 用户消息格式化 | A2 |
| ai/prompt_builder.py | 112 | PromptContext + 渲染 | A3 |
| ai/session_manager.py | 115 | 会话缓存 + 锁字段 | B1 |
| ai/identity.py | 279 | 身份三级确认协调 | B2 |
| ai/world_updater.py | 133 | Step 5a/5b/5c 编排 | B3 |
| ai/background_tasks.py | 164 | 4 个后台任务 + lock | C1 |
| ai/world_tracker.py | 599 | （既有，未动） | — |

**总变化**：core.py 1134 → 579（**-49%**），无逻辑合并、无算法优化、无新功能。

### 2.2 新架构图

```
                    ┌─────────────────────────────┐
                    │     Orchestrator (579行)     │
                    │   chat() 编排 + 异常边界      │
                    │   仅保留: _build_system_prompt │
                    │   (baseline spy 兼容)         │
                    └─────┬───┬───┬───┬───┬──────┘
             依赖注入(构造时) │   │   │   │   │
        ┌─────────┐ ┌───────┴┐ ┌┴─────┐ ┌┴────┐ ┌─┴────────┐
        │ Session │ │ Prompt │ │Ident-│ │World│ │ Background│
        │ Manager │ │ Builder │ │ityFlow│ │Updtr│ │ Tasks    │
        └────┬────┘ └────┬───┘ └──┬───┘ └──┬──┘ └────┬─────┘
             │           │        │        │         │
             ▼           ▼        ▼        ▼         ▼
   ┌────────────┐ ┌──────────┐ ┌────────┐ ┌──────┐ ┌────────────┐
   │ MessageRepo │ │ PromptMgr │ │Profile │ │world_│ │ openai_    │
   │ (database)  │ │ (prompt/) │ │Store   │ │track-│ │ compatible │
   │             │ │ +Character│ │(memory/│ │er.py │ │ .py        │
   │             │ │          │ │stores/)│ │      │ │            │
   └────────────┘ └──────────┘ └────────┘ └──────┘ └────────────┘

   Orchestrator 还持有（既有，零改动）：
   ├─ memory (MemoryManager)      ├─ relationship (RelationshipStore)
   └─ character_loader + prompt_manager
```

**依赖方向**：单向向下，无环。子模块不反向依赖 core（identity.py 用 duck typing 规避 ChatContext 循环）。

---

## 三、红线验证

### 3.1 IdentityFlow Step 6a→7（✅）

```python
# chat() 实际顺序（core.py）:
226:  if await self.identity_flow.has_pending(...)      ← Step 6a
229:      await self.identity_flow.resolve_pending(...) ← 同步 await
300:  system_prompt = self._build_system_prompt(...)    ← Step 7
```

- identity.py 中 `create_task` 匹配仅 1 处 = **docstring 注释**（"禁止后台化"）
- Case 2 断言 `same_turn_name_visible: True`（同一轮 Prompt 能看到确认名字）✓

### 3.2 BackgroundTasks session._lock（✅）

```python
# background_tasks.py:74-77 —— 唯一临界区
async with session._lock:          # LLM 调用完成后才进入
    session.summary = new_summary
    session.messages = session.messages[8:]
    session.pending_count = 0
```

- 锁只在 summarize 使用（唯一写 session 的后台任务）
- LLM 调用（`await summarizer.summarize`）在锁外 —— **不跨 await 持锁** ✓
- batch 快照读取（`messages[:8]`）锁外，与 V3.8.1 读取时点一致 ✓
- session_manager.py:54 `_lock` 字段已就位，其余任务不使用

---

## 四、52 Observation Regression（真实 LLM）

| 类别 | n | avg chars | avg sents | AI 暴露 | 虚构 | 与 OC-3 对比 |
|------|:--:|:--:|:--:|:--:|:--:|:--:|
| 日常 | 17 | 8.2 | 1.65 | **0** | **0** | OC-3: 9.2 → ✅ 接近 V3.7 基线 8.3 |
| 情绪 | 18 | 19.3 | 2.33 | **0** | **0** | OC-3: 23.4 → ✅ 正常波动 |
| 文学 | 17 | 28.1 | 2.83 | **0** | **0** | OC-3: 28.2 → ✅ 几乎一致 |

**结论**：结构拆分后表达基线无回归，红线（AI 暴露/虚构）保持零。

---

## 五、Stage 0 完成标准核对

| # | 完成标准 | 状态 |
|---|---------|:--:|
| 1 | core.py ≤ 350 行（纯编排） | ⚠️ 579 行（含既有公开 API + _build_system_prompt；**按用户决定不强拆**） |
| 2 | 7 个新模块文件 | ✅ intent/message_formatter/prompt_builder/session_manager/identity/world_updater/background_tasks |
| 3 | 37/37 测试通过（断言零改动） | ✅ |
| 4 | 行为一致性测试（DB checksum） | ✅ ALL PASS |
| 5 | 52 观察用例无差异 | ✅ 红线全零，表达基线一致 |
| 6 | git diff 不触及 memory/ relationship/ prompt/templates/ database/ | ✅ |

---

## 六、Stage 0 过程中发现并记录的问题

| # | 发现 | 处理 |
|---|------|------|
| 1 | `generate_timeline_if_needed` 无 return → consolidate 链路从不触发（V3 既有） | 记录为真实行为（baseline `rel_memories==0` 断言固化） |
| 2 | `_build_system_prompt` 是同步方法（chat() 无 await） | 迁移时保持同步（PromptBuilder.build 同步） |
| 3 | 两次删除脚本事故（误删 B2 壳 / `_dump_prompt` + @staticmethod） | 从 git 恢复 + AST 完整性验证 |

---

## 七、Stage 0 后架构结论

**已完成**：上帝对象拆分为 7 个职责单一的子模块，Orchestrator 只做编排。行为 100% 一致（测试 + checksum + 观察三重验证）。

**未做（按用户指示）**：
- 不强拆 chat() 编排（不为了行数拆）
- 不进入 C2b/c（SessionManager 锁模型、world_tracker 拆分等）

**下一步建议**：V4 Stage 1（SelfPersonality）或按 V4_MIGRATION_PLAN 推进。

**提交记录**：Stage 0 共 8 个 commit（A1-A4, B1-B3, C1, C2a），当前 HEAD `60a4627`。
