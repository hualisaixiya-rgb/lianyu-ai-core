"""API 聊天接口测试。

使用 FastAPI TestClient，不依赖真实 LLM 网络。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_chat_endpoint_returns_reply():
    """POST /api/v1/chat 应返回 reply 字段。

    注：此测试依赖真实 LLM（会走 DeepSeek API），
    需要有效的 .env 配置才能通过。
    """
    resp = client.post("/api/v1/chat", json={
        "user_id": "test-001",
        "message": "你好",
    })
    # 即使 LLM 不可用，也不应返回 422（那是请求格式错误）
    assert resp.status_code != 422, f"请求格式错误: {resp.text}"
    data = resp.json()
    assert "reply" in data
    assert isinstance(data["reply"], str)
    assert len(data["reply"]) > 0


def test_chat_empty_message_rejected():
    """空消息应被 Pydantic 校验拒绝（422）。"""
    resp = client.post("/api/v1/chat", json={
        "user_id": "test-001",
        "message": "",
    })
    assert resp.status_code == 422


def test_chat_missing_user_id_rejected():
    """缺少 user_id 应被拒绝（422）。"""
    resp = client.post("/api/v1/chat", json={
        "message": "你好",
    })
    assert resp.status_code == 422


def test_chat_message_too_long_rejected():
    """超长消息应被拒绝（422）。"""
    resp = client.post("/api/v1/chat", json={
        "user_id": "test-001",
        "message": "x" * 2001,
    })
    assert resp.status_code == 422


def test_health_still_works():
    """确认 health 端点未被破坏。"""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_swagger_docs_accessible():
    """确认 OpenAPI 文档可访问。"""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    data = resp.json()
    paths = data.get("paths", {})
    assert "/api/v1/chat" in paths, f"chat 端点未出现在 OpenAPI 文档中，路径: {list(paths.keys())}"
    assert "post" in paths["/api/v1/chat"]
