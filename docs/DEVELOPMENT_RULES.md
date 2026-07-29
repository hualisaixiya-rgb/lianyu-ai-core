# 开发规则

> 回答"以后怎么修改这个项目"。防止打补丁式开发。

---

## 新功能加入流程

```
需求 → 判断属于哪个模块 → 判断影响范围 → 判断是否破坏架构 → 开始编码
```

### 小型修改（如调整 system.yaml 一句话）

1. 直接修改
2. 跑 `pytest tests/`
3. 如果测试失败 → 先更新测试，再更新代码

### 中型修改（如新增一个 Memory Store 方法）

1. 明确：这个方法属于哪个 Store？不要放错位置
2. 写方法 → 更新 docstring → 跑测试
3. 如果有调用方受影响 → 更新调用方

### 大型修改（如修改 `ai/core.py` 的 chat 流程）

1. **先设计方案**（可以写在文档或 Issue 中）
2. 确认不引入新的技术债
3. 人工确认方案
4. 编码
5. 全量测试 + 实际聊天观察 ≥ 1 天
6. 更新 CHANGELOG

---

## 核心模块保护

以下模块修改前**必须**先做影响分析：

| 模块 | 保护原因 |
|------|---------|
| `database/models/` | ORM 变更影响所有下游；需要迁移计划 |
| `memory/extractor.py` | Profile + LongMemory 写入链路入口 |
| `memory/stores/` | 数据库直接读写，Bug 会污染数据 |
| `ai/core.py` | 中枢，1122 行，改动影响全部消息流 |
| `prompt/templates/system.yaml` | 直接影响 LLM 行为 |
| `adapters/telegram/bot.py` | 生产环境入口 |

---

## 哪些模块不能随便修改

| 模块 | 规则 | 原因 |
|------|------|------|
| `system.yaml` 人格规则 | 每次改动不超过 10 行；记录到 CHANGELOG | V3.7 已收敛，避免反复振荡 |
| `ai/core.py` 的 `chat()` 方法 | 不新增超过 20 行的方法；优先抽出独立模块 | 已是上帝对象 |
| `database/models/` 的表结构 | ALTER TABLE 前确认不影响已有数据 | SQLite 不支持事务性 DDL |
| `adapters/telegram/bot.py` 的消息处理 | 不在此文件中放 AI 逻辑 | 保持适配器轻量 |

---

## 测试要求

| 改动范围 | 测试要求 |
|---------|---------|
| system.yaml | `pytest tests/` + 实际聊天测试 ≥ 1 轮 |
| memory/ | `pytest tests/` + 检查数据库状态 |
| ai/core.py | `pytest tests/` + 多种意图测试 |
| database/ | `pytest tests/` + 新库初始化测试 |
| adapters/ | 启动 Bot 实际收发消息 |

**最低要求**：`pytest tests/` 全部通过（当前 32 项）。

---

## 文档同步要求

| 改动 | 需更新文档 |
|------|----------|
| 新增模块 | ARCHITECTURE.md 模块表 |
| 版本发布 | CHANGELOG.md |
| 阶段变化 | V3_STATUS.md |
| Persona 修改 | CHARACTER_EXPRESSION_BASELINE.md |
| 重大设计决策 | ARCHITECTURE_DECISIONS.md（新增 ADR） |

### 文档同步自动检查

任何代码修改完成后，自动运行此检查：

```
□ PROJECT_OVERVIEW    — 项目目标是否改变？
□ ARCHITECTURE        — 模块职责、数据流是否变化？
□ ARCHITECTURE_DECISIONS — 是否产生新的设计决策？
□ DEVELOPMENT_RULES   — 开发规则是否需要更新？
□ CHANGELOG           — 是否需要记录版本变化？
□ V3_STATUS           — 已完成/开发中/暂停状态是否变化？
```

如需更新，**主动提示**，不允许长期不同步。

### 文档优先级

开发时统一遵循以下优先级。如果当前需求与高优先级文档冲突，**不得直接实现**：

```
1. PROJECT_OVERVIEW      — 项目目标（最高）
2. ARCHITECTURE           — 系统架构
3. ARCHITECTURE_DECISIONS — 已记录的设计决策
4. DEVELOPMENT_RULES      — 开发规则
5. AI_DEVELOPMENT_PROTOCOL — AI 协作协议
6. V3_STATUS              — 当前状态
7. CHANGELOG              — 版本记录
8. 当前开发需求            —（最低）
```

---

## 版本冻结机制

当一个版本进入稳定阶段（如当前 V3.7）：

**默认**：不新增核心功能。

**只允许**：
- Bug 修复
- 表达层微调（system.yaml ≤ 10 行）
- 稳定性优化
- 文档完善

**如需新增大型功能**（如 Emotion、Vision、Agent、Voice、多角色）：
- 必须开启新版本规划（V4）
- 先在 V3_STATUS.md 中标记"计划中"
- 不在当前冻结版本中实现

---

## 禁止事项

- ❌ 在 `ai/core.py` 中添加超过 20 行的新方法
- ❌ 直接 `from database.models import X` 在 memory/ 之外操作 DB
- ❌ 新增 hardcoded 平台名（`"telegram"` 等）
- ❌ 在 `system.yaml` 中添加"不要使用：X, Y, Z"式黑名单
- ❌ 不经 `pytest` 验证直接部署
- ❌ 直接修改服务器代码
- ❌ 在 `.env` 中提交真实 API Key

---

## 代码风格

- 用 `ruff` 保持代码风格（E, F, I, N, W, UP, B, C4, SIM 规则）
- 异步函数必须声明返回类型
- `except Exception: pass` 只允许在非关键路径（存档、日志等）
- 新增 `asyncio.create_task` 必须包裹 `asyncio.wait_for` + error logging
