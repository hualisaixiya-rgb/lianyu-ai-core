"""SQLite 记忆存储实现。

基于 SQLAlchemy 的 MemoryRecord 模型实现 MemoryStore 接口。
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.memory import MemoryRecord
from database.session import AsyncSessionLocal
from memory.base import MemoryItem, MemoryStore
from loguru import logger


class SQLiteMemoryStore(MemoryStore):
    """SQLite 记忆存储。

    实现 MemoryStore 接口，使用 SQLAlchemy AsyncSession 操作数据库。
    """

    async def add(
        self,
        platform: str,
        platform_user_id: str,
        key: str,
        value: str,
        importance: int = 5,
    ) -> None:
        """添加一条记忆记录。

        如果 key 已存在则更新内容。
        """
        async with AsyncSessionLocal.get_session() as session:
            # 检查是否已存在同 key 记录
            stmt = select(MemoryRecord).where(
                MemoryRecord.platform == platform,
                MemoryRecord.platform_user_id == platform_user_id,
                MemoryRecord.key == key,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.value = value
                existing.importance = importance
                logger.debug(f"更新记忆: {key}")
            else:
                record = MemoryRecord(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    key=key,
                    value=value,
                    importance=importance,
                )
                session.add(record)
                logger.debug(f"新增记忆: {key}")

    async def search(
        self,
        platform: str,
        platform_user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryItem]:
        """搜索相关记忆。

        当前使用简单的 LIKE 关键词匹配。
        未来可替换为向量相似度搜索。
        """
        async with AsyncSessionLocal.get_session() as session:
            # 将查询单词用于模糊匹配
            keywords = query.strip().split()
            stmt = (
                select(MemoryRecord)
                .where(
                    MemoryRecord.platform == platform,
                    MemoryRecord.platform_user_id == platform_user_id,
                )
                .order_by(MemoryRecord.importance.desc())
                .limit(top_k * 2)  # 多取一些用于过滤
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            # 简单的关键词评分过滤
            items: list[MemoryItem] = []
            for record in records:
                # 如果有关键词匹配，加分
                score = 0
                search_text = f"{record.key} {record.value}".lower()
                for kw in keywords:
                    if kw.lower() in search_text:
                        score += 1

                items.append(
                    MemoryItem(
                        key=record.key,
                        value=record.value,
                        importance=record.importance + score,
                    )
                )

            # 按（重要性 + 关键词匹配分）降序排列，取 top_k
            items.sort(key=lambda x: x.importance, reverse=True)
            return items[:top_k]

    async def list_all(
        self,
        platform: str,
        platform_user_id: str,
    ) -> list[MemoryItem]:
        """列出用户所有记忆。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = (
                select(MemoryRecord)
                .where(
                    MemoryRecord.platform == platform,
                    MemoryRecord.platform_user_id == platform_user_id,
                )
                .order_by(MemoryRecord.importance.desc())
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            return [
                MemoryItem(
                    key=r.key,
                    value=r.value,
                    importance=r.importance,
                )
                for r in records
            ]

    async def delete(
        self,
        platform: str,
        platform_user_id: str,
        key: str,
    ) -> bool:
        """删除一条记忆。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = delete(MemoryRecord).where(
                MemoryRecord.platform == platform,
                MemoryRecord.platform_user_id == platform_user_id,
                MemoryRecord.key == key,
            )
            result = await session.execute(stmt)
            deleted = result.rowcount > 0
            if deleted:
                logger.debug(f"删除记忆: {key}")
            return deleted

    async def clear(
        self,
        platform: str,
        platform_user_id: str,
    ) -> int:
        """清除用户所有记忆。"""
        async with AsyncSessionLocal.get_session() as session:
            stmt = delete(MemoryRecord).where(
                MemoryRecord.platform == platform,
                MemoryRecord.platform_user_id == platform_user_id,
            )
            result = await session.execute(stmt)
            count = result.rowcount
            logger.info(f"清除 {count} 条记忆: [{platform}:{platform_user_id}]")
            return count
