"""应用主入口。

FastAPI 应用工厂 + 启动脚本。
通过 `python -m app.main` 启动。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.router import api_router
from app.lifecycle import shutdown, startup
from config.settings import get_settings
from utils.logger import setup_logger


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。

    使用工厂模式，便于测试和多环境部署。

    Returns:
        配置好的 FastAPI 实例
    """
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期管理。"""
        await startup()
        yield
        await shutdown()

    app = FastAPI(
        title="绘梨衣 AI Core",
        description="支持多平台接入的 AI Agent 核心引擎",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 注册路由
    app.include_router(api_router)

    return app


# 模块级单例
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    setup_logger(settings.app.log_level)

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app.debug,
        log_level=settings.app.log_level.lower(),
    )
