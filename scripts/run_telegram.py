#!/usr/bin/env python
"""Telegram Bot 启动脚本。

独立运行 Telegram Bot，不依赖 FastAPI 服务。

使用方式：
    uv run python scripts/run_telegram.py

前提：
    1. .env 中已配置 TELEGRAM_BOT_TOKEN
    2. 已通过 @BotFather 创建 Bot 并获取 Token
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from database.engine import init_db
from adapters.telegram.bot import TelegramBot
from utils.logger import setup_logger, get_logger


async def main() -> None:
    """启动 Telegram Bot。"""
    setup_logger("INFO")
    logger = get_logger()

    settings = get_settings()

    # 检查 Token
    if not settings.telegram.bot_token or settings.telegram.bot_token == "placeholder-token":
        logger.error("TELEGRAM_BOT_TOKEN 未配置。请在 .env 中设置。")
        print("错误：请先在 .env 文件中配置 TELEGRAM_BOT_TOKEN")
        print()
        print("获取 Token 的步骤：")
        print("  1. 在 Telegram 中搜索 @BotFather")
        print("  2. 发送 /newbot")
        print("  3. 按提示输入 Bot 名称和用户名")
        print("  4. 复制得到的 Token，粘贴到 .env 的 TELEGRAM_BOT_TOKEN=")
        sys.exit(1)

    # 检查 AI API Key
    if not settings.ai.api_key or settings.ai.api_key == "sk-placeholder-key":
        logger.error("AI_LLM_API_KEY 未配置。请在 .env 中设置。")
        sys.exit(1)

    # 初始化数据库
    await init_db()
    logger.info("数据库已初始化")

    # 启动 Bot
    bot = TelegramBot()
    logger.info(f"启动 Telegram Bot...")
    print(f"Bot 已启动！在 Telegram 中找到你的 Bot 并发送消息。")
    print(f"按 Ctrl+C 停止。")

    _started = False
    try:
        await bot.start()
        _started = True
        print("按 Ctrl+C 停止。")
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n正在停止...")
        if _started:
            await bot.stop()
    except Exception as e:
        logger.error(f"启动失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
