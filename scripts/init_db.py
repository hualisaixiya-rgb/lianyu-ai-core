#!/usr/bin/env python
"""数据库初始化脚本。

创建所有 ORM 模型对应的数据库表。
独立于应用启动流程，可用于首次部署或重置。
"""

import asyncio
import sys
from pathlib import Path

# 将项目根目录加入 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.engine import init_db
from utils.logger import setup_logger
from loguru import logger


async def main():
    """主函数：初始化数据库。"""
    setup_logger("INFO")
    logger.info("开始初始化数据库...")

    await init_db()

    logger.info("数据库初始化完成！")


if __name__ == "__main__":
    asyncio.run(main())
