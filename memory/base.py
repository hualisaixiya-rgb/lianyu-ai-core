"""记忆存储抽象基类。

定义记忆存储的标准接口，方便以后替换后端。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class MemoryItem:
    """一条记忆条目。

    Attributes:
        key: 记忆关键词，用于检索匹配
        value: 记忆内容
        importance: 重要性分数（1-10）
    """

    key: str
    value: str
    importance: int = 5


class MemoryStore(ABC):
    """记忆存储抽象基类。

    所有记忆后端必须实现此接口。
    当前实现：SQLite
    未来实现：ChromaDB / Qdrant / pgvector / Milvus
    """

    @abstractmethod
    async def add(
        self,
        platform: str,
        platform_user_id: str,
        key: str,
        value: str,
        importance: int = 5,
    ) -> None:
        """添加一条记忆。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            key: 记忆关键词
            value: 记忆内容
            importance: 重要性分数
        """
        ...

    @abstractmethod
    async def search(
        self,
        platform: str,
        platform_user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryItem]:
        """搜索相关记忆。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            query: 搜索查询文本
            top_k: 返回最相关的 K 条记忆

        Returns:
            匹配的记忆条目列表（按重要性降序）
        """
        ...

    @abstractmethod
    async def list_all(
        self,
        platform: str,
        platform_user_id: str,
    ) -> list[MemoryItem]:
        """列出用户所有记忆。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID

        Returns:
            该用户的所有记忆条目
        """
        ...

    @abstractmethod
    async def delete(
        self,
        platform: str,
        platform_user_id: str,
        key: str,
    ) -> bool:
        """删除一条记忆。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID
            key: 要删除的记忆关键词

        Returns:
            是否成功删除
        """
        ...

    @abstractmethod
    async def clear(
        self,
        platform: str,
        platform_user_id: str,
    ) -> int:
        """清除用户所有记忆。

        Args:
            platform: 平台标识
            platform_user_id: 平台侧用户 ID

        Returns:
            删除的记录数
        """
        ...
