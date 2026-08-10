"""聊天接口。

POST /api/v1/chat —— 外部客户端（桌宠/网页/语音/微信等）通过 HTTP 调用绘梨衣。

流程：
    HTTP 请求 → ChatContext → AICore.chat() → ChatResponse → HTTP 响应
"""

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from ai.core import AICore, ChatContext
from utils.response_renderer import render_for_user

router = APIRouter(tags=["chat"])

# ---- AICore 懒加载单例 ----
# 首次请求时才初始化（避免 import 时做重 IO）
_core: AICore | None = None


def get_core() -> AICore:
    """获取 AICore 单例。"""
    global _core
    if _core is None:
        _core = AICore()
    return _core


# ---- 请求 / 响应模型 ----

class ChatRequest(BaseModel):
    """聊天请求。"""

    user_id: str = Field(..., min_length=1, max_length=64, description="用户唯一标识")
    message: str = Field(..., min_length=1, max_length=2000, description="用户消息")


class ChatReply(BaseModel):
    """聊天响应。"""

    reply: str = Field(..., description="AI 回复内容")


# ---- 端点 ----

@router.post("/chat", response_model=ChatReply)
async def chat(req: ChatRequest) -> ChatReply:
    """处理聊天请求，返回 AI 回复。

    接收任意客户端（桌宠/网页/语音/微信等）的消息，
    委托给 AICore 推理，返回回复文本。
    """
    try:
        ctx = ChatContext(
            platform="web",
            platform_user_id=req.user_id,
            message=req.message,
        )
        resp = await get_core().chat(ctx)
        # 表达层：修复格式漂移 + 按场景调节表达强度（用户消息上下文）后返回
        return ChatReply(reply=render_for_user(resp.content, req.message))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 服务异常: {e}")
