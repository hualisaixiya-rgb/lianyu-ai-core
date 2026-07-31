# V3 当前状态

> 回答"现在项目处于什么阶段"。每次阶段变化时更新。

**最后更新**：2026-07-31

---

## 当前阶段

**V3.8 稳定化完成**。5 项已知问题已修复，32 测试全过。准备进入 V4。

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
| V4 架构设计 | ✅ | V4_DESIGN / V4_CHARACTER_STATE / V4_SELF_PERSONALITY / V4_MEMORY_EVOLUTION / V4_ACCEPTANCE_TESTS |
| relationship.touch 合并 | ✅ V3.8 | 消除重复调用 |
| 死代码清理 | ✅ V3.8 | 删除 build_system_prompt() + memory.yaml |
| except Exception 日志 | ✅ V3.8 | 9 处 pass → logger.debug |
| create_task timeout | ✅ V3.8 | 5 处添加 30s timeout |
| Profile 标记词扩展 | ✅ V3.8 | 新增日常表达标记词 |

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
| 1 | `ai/core.py` 1122 行上帝对象 | 🟡 | V4 Stage 0 拆分 |
| 2 | `test_fresh.db` schema 未同步 | 🟢 | 低优先级 |
| 3 | Tools 未接入 chat 流程 | 🟢 | V4 |
| 4 | 关系理解 3 层 LLM 链路（Summary→Timeline→RelationshipMemory）误差累积 | 🟡 | V4 优化 |
| 5 | `ExpressionTracker` 未接入 | 🟢 | V4 接入或删除 |

---

## 下一阶段计划

| 优先级 | 事项 | 预计版本 |
|--------|------|---------|
| P0 | V4 Stage 0：ai/core.py 拆分 | V4.0 |
| P1 | V4 Stage 1：Phase 2 SelfPersonality | V4.0 |
| P2 | V4 Stage 2：Phase 1 CharacterState | V4.0 |
| P2 | V4 Stage 3：Phase 4 MemoryEvolution | V4.0 |

---

## 发布状态

| 环境 | 版本 | 状态 |
|------|------|------|
| 主机（开发） | V3.8 | 稳定化完成，准备 V4 |
| 服务器（生产） | V3.4（最后发布的稳定版） | 运行中 |
| GitHub | V3.8 | 待推送 |
