# 项目总览

## 项目名称

**LianyuAI Core**（绘梨衣 AI Core）

## 项目定位

面向虚拟角色长期人格、记忆、关系模拟的 AI Core 引擎。

不是普通聊天机器人。核心目标不是"回答问题"或"完成任务"，而是：

1. **长期人格稳定**：角色在连续数周的对话中保持一致的语气、性格、表达模式
2. **真实记忆系统**：区分"用户事实"和"AI 表达"，存储用户信息但不产生幻觉污染
3. **关系模拟**：追踪用户与角色的关系变化（Timeline + Relationship Memory）
4. **多平台接入**：Telegram / CLI / HTTP API / Voice，通过适配器模式统一接入

## 当前角色

**上杉绘梨衣**（《龙族》），16 岁。安静、真诚、温柔、社交笨拙、表达克制。

角色定义在 `character/characters/eryi.yaml`，通过 `system.yaml` 控制表达层行为。

## 核心目标

| 目标 | 状态 |
|------|------|
| 人格稳定性 | V3.7 表达层重建完成，10 个日常场景示例 |
| 记忆系统 | V3 六层架构（Profile / LongMemory / Timeline / Relationship / WorldState / ActiveTopics） |
| 关系追踪 | Timeline + RelationshipMemory + EmotionTrend |
| 多平台 | Telegram Bot + HTTP API + CLI |
| 记忆安全 | source 标记、context_visible 过滤、pending identity |

## 不做什么

- 不是通用 AI 助手（不回答问题库、不查资料）
- 不是客服系统
- 不是任务执行引擎
- 不是多角色平台（当前仅支持单个角色"绘梨衣"）
- 不追求并发性能（单用户亲密陪伴场景）

## 当前版本

**V3.7**（2026-07-28）

- 表达层：极致精简（Persona 22 行 + 10 个日常示例）
- Memory：V3.5 记忆安全补丁完成
- 测试：32/32 通过
- 部署：主机开发环境测试中，未发布服务器

## 长期方向

| 阶段 | 目标 |
|------|------|
| V3.7.x | 表达层微调 + 稳定性观察 |
| V3.8 | bug 修复 + 测试补充 |
| V4.0 | `ai/core.py` 拆分 + Provider 抽象 + Tools 集成 |

## 技术栈

- Python 3.12+ / FastAPI / SQLAlchemy 2.0 (async) / SQLite (aiosqlite)
- python-telegram-bot / httpx / pydantic-settings
- DeepSeek API（OpenAI 兼容协议）
- Voice: faster-whisper + GPT-SoVITS / Edge-TTS

## 相关文档

| 文档 | 用途 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构 |
| [DEVELOPMENT_RULES.md](DEVELOPMENT_RULES.md) | 开发规则 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变化 |
| [V3_STATUS.md](V3_STATUS.md) | 当前状态 |
| [CHARACTER_EXPRESSION_BASELINE.md](CHARACTER_EXPRESSION_BASELINE.md) | 人格表达基准 |
| [AI_DEVELOPMENT_PROTOCOL.md](AI_DEVELOPMENT_PROTOCOL.md) | AI 协作协议 |
| [V3.6.1_DEV_STATUS.md](V3.6.1_DEV_STATUS.md) | V3.5~V3.6.1 开发记录 |
