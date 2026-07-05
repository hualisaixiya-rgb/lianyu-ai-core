#!/usr/bin/env python
"""Passive Agent Launcher —— 低频主动角色代理启动脚本。

与 Telegram Bot 共用同一个进程。
Bot 负责被动回复，Agent 负责偶尔主动发消息。

使用方式：
    uv run python scripts/run_agent.py

前提：
    .env 中已配置 TELEGRAM_BOT_TOKEN 和 AI_LLM_API_KEY
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.scheduler import AgentScheduler
from config.settings import get_settings
from database.engine import init_db
from adapters.telegram import TelegramBot
from utils.logger import setup_logger, get_logger


async def main() -> None:
    """启动 Telegram Bot + Passive Agent。"""
    setup_logger("INFO")
    logger = get_logger()

    settings = get_settings()

    # 检查配置
    if not settings.ai.api_key or settings.ai.api_key == "sk-placeholder-key":
        logger.error("AI_LLM_API_KEY 未配置")
        sys.exit(1)
    if not settings.telegram.bot_token or settings.telegram.bot_token == "placeholder-token":
        logger.error("TELEGRAM_BOT_TOKEN 未配置")
        sys.exit(1)

    # 初始化数据库（同时创建 chat + agent 表）
    await init_db()
    logger.info("数据库已初始化")

    # 初始化 Bot
    logger.info("启动 Telegram Bot...")
    bot = TelegramBot()

    # 初始化 Agent Scheduler 并绑定同一个 Bot
    scheduler = AgentScheduler(tick_minutes=10)

    try:
        # 先启动 Bot
        await bot.start()
        # 等 Bot 完全启动后再绑定
        await asyncio.sleep(1)
        scheduler.bind_telegram(bot._app)

        logger.info("=" * 40)
        logger.info("绘梨衣 Passive Agent 已启动")
        logger.info(f"  Tick 间隔: 10 分钟")
        logger.info(f"  每日主动消息上限: 5 条")
        logger.info(f"  冷却时间: 30 分钟")
        logger.info("  Bot 已就绪，等待被动消息 + 主动 tick")
        logger.info("=" * 40)

        # 并行运行 Bot 轮询 + Agent 调度
        # Bot 已在 start() 中启动了 polling，这里我们只需要跑 scheduler
        await scheduler.run_forever()

    except KeyboardInterrupt:
        print("\n正在停止...")
    except Exception as e:
        logger.error(f"启动失败: {e}")
    finally:
        scheduler.stop()
        await bot.stop()
        logger.info("已停止")


if __name__ == "__main__":
    asyncio.run(main())
