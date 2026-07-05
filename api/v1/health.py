"""健康检查接口。

提供应用状态检查，用于监控和负载均衡。
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """健康检查端点。

    Returns:
        {"status": "ok", "version": "0.1.0"}
    """
    return {
        "status": "ok",
        "version": "0.1.0",
    }
