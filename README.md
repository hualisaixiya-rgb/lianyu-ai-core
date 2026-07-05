# 绘梨衣 AI Core

> 支持多平台接入的 AI Agent 核心引擎

[![Python](https://img.shields.io/badge/Python-3.12+-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green)](https://fastapi.tiangolo.com)
[![uv](https://img.shields.io/badge/uv-package%20manager-purple)](https://docs.astral.sh/uv)

## 项目简介

这是一个**真正独立的 AI Core**，而不是简单的 Telegram Bot。

Telegram 只是聊天入口之一，以后还可能接入微信、网页、QQ 等。

### 架构亮点

```
┌──────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                 │
├──────────────────────────────────────────────────────┤
│  Telegram  │  微信 (未来)  │  Web (未来)  │  QQ (未来) │
│  Adapter   │   Adapter     │   Adapter    │  Adapter   │
├────────────┴───────────────┴──────────────┴───────────┤
│                     AI Core                           │
│  ┌──────────┬───────────┬──────────┬──────────┐     │
│  │  Memory  │ Character │  Prompt  │  Tools   │     │
│  └──────────┴───────────┴──────────┴──────────┘     │
├──────────────────────────────────────────────────────┤
│                 Database (SQLAlchemy)                  │
└──────────────────────────────────────────────────────┘
```

## 目录结构

```
lianyu-ai-core/
├── app/                    # FastAPI 应用入口 + 生命周期
│   ├── main.py
│   └── lifecycle.py
├── ai/                     # AI Core - 核心推理引擎
│   ├── core.py             # 统一推理入口 AICore
│   └── providers/          # LLM 提供商适配
│       └── openai_compatible.py
├── memory/                 # 长期记忆（独立模块）
│   ├── base.py             # MemoryStore 抽象基类
│   ├── manager.py          # 记忆管理器
│   └── stores/
│       └── sqlite_store.py # SQLite 记忆后端
├── character/              # 角色系统（YAML 配置）
│   ├── loader.py           # CharacterLoader
│   └── characters/         # 角色配置文件
├── prompt/                 # Prompt 管理
│   ├── manager.py          # PromptManager
│   └── templates/          # Prompt 模板（YAML）
├── telegram/               # Telegram Adapter
│   ├── bot.py
│   └── handlers/
├── database/               # 数据库
│   ├── engine.py
│   ├── session.py
│   └── models/             # ORM 模型
├── config/                 # 配置管理（Pydantic Settings）
│   └── settings.py
├── tools/                  # 工具调用
│   ├── registry.py         # ToolRegistry
│   └── builtin/            # 内置工具
├── utils/                  # 工具函数
│   └── logger.py           # Loguru 日志
├── api/                    # FastAPI 路由
│   └── v1/
├── tests/                  # 测试
├── scripts/                # 脚本
├── docker/                 # Docker 配置
├── pyproject.toml
├── .env.example
└── Makefile
```

## 快速开始

### 前置要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装 uv

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 安装项目

```bash
cd lianyu-ai-core

# 安装全部依赖（含开发工具）
uv sync

# 或仅安装生产依赖
uv sync --no-dev
```

### 配置

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 填入真实的 API Key 和 Bot Token
```

### 运行

```bash
# 方式 1：直接用 Makefile
make run

# 方式 2：手动运行
uv run python -m app.main
```

FastAPI 服务启动后访问 http://localhost:8000/api/v1/health 验证。

### 运行测试

```bash
make test
# 或
uv run pytest -v
```

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI | 高性能异步 Web 框架 |
| Telegram | python-telegram-bot | 异步 Telegram Bot 库 |
| LLM | OpenAI Compatible API | 兼容 DeepSeek/OpenAI/Qwen |
| 数据库 | SQLAlchemy + SQLite | 异步 ORM，后续可迁 PostgreSQL |
| 配置 | Pydantic Settings | 类型安全的配置管理 |
| 日志 | Loguru | 结构化日志 |
| 包管理 | uv | 现代化 Python 包管理器 |
| 容器化 | Docker + Docker Compose | 一键部署 |

## 许可证

MIT License
