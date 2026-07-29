# V3 当前状态

> 回答"现在项目处于什么阶段"。每次阶段变化时更新。

**最后更新**：2026-07-29

---

## 当前阶段

**V3.7 稳定化阶段**。代码冻结。仅做表达层微调 + 稳定性观察。

---

## 已完成

| 模块 | 状态 | 备注 |
|------|------|------|
| Persona 表达层 | ✅ V3.7 | 22 行精简 Prompt + 10 个日常示例 |
| Memory 六层架构 | ✅ V3.5.1 | Profile / LongMemory / Timeline / Relationship / WorldState / ActiveTopics |
| Memory Source 标记 | ✅ V3.5 | source 从 extractor → manager → storage 透传 |
| LLM Timeout | ✅ V3.5 | 60s total / 10s connect |
| Summary/Timeline 隔离 | ✅ V3.5 | 主语"你们"→"对方"，旧数据 V3.5 cutoff |
| Intent 路由 | ✅ V3 | GREETING / IDENTITY_CHECK / RECALL_PAST / DEEP_TALK / DAILY_CHAT |
| Pending Identity | ✅ V3 | profile_history 三级确认（candidate → pending → confirmed） |
| context_visible 过滤 | ✅ V3 | 身份声明不进入 LLM 上下文 |
| Telegram Bot | ✅ V3.5 | HTTPXRequest 自定义 timeout + connection pool |
| HTTP API | ✅ V3.6 | /api/v1/chat 端点 |
| 测试 | ✅ 32/32 | pytest 全部通过 |
| 项目文档 | ✅ | PROJECT_OVERVIEW / ARCHITECTURE / DEVELOPMENT_RULES / CHANGELOG / AI_DEVELOPMENT_PROTOCOL |

---

## 正在开发

| 模块 | 状态 | 备注 |
|------|------|------|
| 表达层观察 | 🔵 观察中 | V3.7 部署后观察文学化是否解决 |

---

## 暂停开发

| 模块 | 原因 | 计划恢复 |
|------|------|---------|
| Voice（语音） | 模块完整但未接入聊天流程（仅在 scripts/ 中使用） | V4 |
| Tools 系统 | ToolRegistry + calculator + read_image 已实现但未接入 chat 流程 | V4 |
| Agent 主动消息 | scheduler 已实现但默认不启用 | V4 |
| 向量搜索 | 当前 LIKE 匹配，设计预留了向量搜索接口 | V4 |

---

## 已知问题

| # | 问题 | 严重度 | 计划 |
|---|------|--------|------|
| 1 | `user_profiles` 为空 — 用户姓名从未持久化 | 🟡 | V3.8 修复 |
| 2 | `ai/core.py` 1122 行上帝对象 | 🟡 | V4 拆分 |
| 3 | 22 个 `except Exception: pass` | 🟡 | 持续改进 |
| 4 | `test_fresh.db` schema 未同步 | 🟢 | 低优先级 |
| 5 | Tools 未接入 chat 流程 | 🟢 | V4 |
| 6 | 关系理解 3 层 LLM 链路（Summary→Timeline→RelationshipMemory）误差累积 | 🟡 | V4 优化 |
| 7 | `asyncio.create_task` 5 处无 timeout 包裹 | 🟡 | V3.8 修复 |

---

## 下一阶段计划

| 优先级 | 事项 | 预计版本 |
|--------|------|---------|
| P0 | V3.7 实际聊天观察 3~7 天 | 当前 |
| P0 | 数据库审计（Timeline 是否仍产生污染） | V3.7 |
| P1 | 修复 `user_profiles` 为空 | V3.8 |
| P1 | `asyncio.create_task` timeout 包裹 | V3.8 |
| P2 | `ai/core.py` 拆分（IntentRouter + PromptBuilder + PostProcessPipeline） | V4.0 |
| P2 | Provider 抽象 + retry 机制 | V4.0 |
| P2 | Tools 接入 chat 流程 | V4.0 |

---

## 发布状态

| 环境 | 版本 | 状态 |
|------|------|------|
| 主机（开发） | V3.7 | 测试中 |
| 服务器（生产） | V3.4（最后发布的稳定版） | 运行中 |
| GitHub | V3.7 | 已推送（commit `3183483`） |
