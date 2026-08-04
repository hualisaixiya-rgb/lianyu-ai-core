"""会话管理模块。

V4 Stage 0 Phase B1：从 ai/core.py 纯搬移，行为 100% 一致。

SessionManager 负责：
- session key 构造
- session 内存缓存
- 历史加载（首次从 DB 加载）

ConversationSession 字段与 V3.8.1 完全一致。
asyncio.Lock 已加入（_lock 字段），但暂不改变任何 append/read 行为，
锁的实际使用留给 Phase C1（BackgroundTasks）。
"""

import asyncio
from dataclasses import dataclass, field

from loguru import logger

from ai.world_tracker import WorldState, ActiveTopics, ExpressionTracker
from database.repository import MessageRepository


# 每个会话加载的历史消息数量上限
MAX_HISTORY_MESSAGES = 16


@dataclass
class ConversationSession:
    """一个用户的对话会话（内存缓存）。

    Attributes:
        messages: 当前窗口内的对话历史（最近 N 条）
        loaded_from_db: 是否已从数据库加载
        summary: 滚动累积的对话摘要（结构化格式）
        pending_count: 自上次摘要后新增的消息数
        world_state: 当前世界状态（Rule Engine 维护，不写 DB）
        active_topics: 活跃话题管理器
        expression_tracker: 表达多样性追踪器
        _no_match_count: 连续未命中 Rule 的轮数
    """

    platform: str
    platform_user_id: str
    messages: list[dict[str, str]] = field(default_factory=list)
    loaded_from_db: bool = False
    summary: str = ""
    pending_count: int = 0
    world_state: WorldState | None = None
    active_topics: ActiveTopics | None = None
    expression_tracker: ExpressionTracker | None = None
    _no_match_count: int = 0
    # 并发锁（Phase C1 BackgroundTasks 使用；当前不改变 append/read 行为）
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionManager:
    """会话生命周期管理。纯内存缓存。

    使用方式：
        manager = SessionManager()
        session = manager.get_or_create(platform, uid)
    """

    def __init__(self) -> None:
        """初始化会话缓存。"""
        self._sessions: dict[str, ConversationSession] = {}

    def _key(self, platform: str, platform_user_id: str) -> str:
        """统一 session key 构造。"""
        return f"{platform}:{platform_user_id}"

    def get_or_create(
        self, platform: str, platform_user_id: str
    ) -> ConversationSession:
        """获取或创建用户会话（内存缓存）。"""
        session_key = self._key(platform, platform_user_id)
        if session_key not in self._sessions:
            self._sessions[session_key] = ConversationSession(
                platform=platform,
                platform_user_id=platform_user_id,
            )
        return self._sessions[session_key]

    def clear(self, platform: str, platform_user_id: str) -> None:
        """清除指定用户的对话历史缓存。"""
        session_key = self._key(platform, platform_user_id)
        self._sessions.pop(session_key, None)
        logger.info(f"会话缓存已清除: {session_key}")

    def get_history(
        self, platform: str, platform_user_id: str
    ) -> list[dict[str, str]]:
        """获取对话历史（只读，从内存缓存）。"""
        session = self.get_or_create(platform, platform_user_id)
        return list(session.messages)

    async def reload_from_db(
        self, platform: str, platform_user_id: str
    ) -> list[dict[str, str]]:
        """从数据库重新加载对话历史。"""
        session_key = self._key(platform, platform_user_id)
        self._sessions.pop(session_key, None)
        db_history = await MessageRepository.get_recent_history(
            platform=platform,
            platform_user_id=platform_user_id,
            limit=MAX_HISTORY_MESSAGES,
        )
        self._sessions[session_key] = ConversationSession(
            platform=platform,
            platform_user_id=platform_user_id,
            messages=db_history,
            loaded_from_db=True,
        )
        return db_history
