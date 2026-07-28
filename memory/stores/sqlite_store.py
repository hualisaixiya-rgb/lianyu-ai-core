"""SQLite 记忆存储实现。

基于 SQLAlchemy 的 MemoryRecord 模型实现 MemoryStore 接口。
"""

import re

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.memory import MemoryRecord
from database.session import AsyncSessionLocal
from memory.base import MemoryItem, MemoryStore
from loguru import logger


def _tokenize(text: str) -> list[str]:
    """简单中文 2-gram 分词 + 英文空格分词。

    "排练好累" → ["排练", "练好", "好累", "排练好累"]
    "hello world" → ["hello", "world", "hello world"]

    不做复杂 NLP，最小可行性实现。
    """
    stripped = text.strip()
    if not stripped:
        return []

    tokens = [stripped]  # 原始短语作为单个 token

    # 中文 2-gram
    if re.search(r"[一-鿿]", stripped):
        chars = list(stripped)
        for i in range(len(chars) - 1):
            bigram = "".join(chars[i:i + 2])
            if bigram not in tokens:
                tokens.append(bigram)

    # 英文/数字空格分词
    alpha_words = re.findall(r"[a-zA-Z0-9]+", stripped)
    for w in alpha_words:
        if w.lower() not in [t.lower() for t in tokens]:
            tokens.append(w.lower())

    return tokens


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
        source: str = "unknown",
        evidence: str | None = None,
    ) -> None:
        """添加一条记忆记录。

        如果 key 已存在则更新内容。
        """
        async with AsyncSessionLocal.get_session() as session:
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
                existing.source = source
                if evidence:
                    existing.evidence = evidence
                logger.debug(f"更新记忆: {key}")
            else:
                record = MemoryRecord(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    key=key,
                    value=value,
                    importance=importance,
                    source=source,
                    evidence=evidence,
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
        """搜索相关记忆（V3.5 相关性评分）。

        搜索范围：key + value + evidence
        评分：关键词命中 × 2 + source 权重 + 时间加分
        无命中时返回空列表，不 fallback 全量注入。
        """
        async with AsyncSessionLocal.get_session() as session:
            stmt = (
                select(MemoryRecord)
                .where(
                    MemoryRecord.platform == platform,
                    MemoryRecord.platform_user_id == platform_user_id,
                )
                .order_by(MemoryRecord.importance.desc())
                .limit(top_k * 3)  # 多取一些用于评分过滤
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            # V3.5: 简单中文 2-gram 分词 + 英文空格分词
            keywords = _tokenize(query)

            # V3.5: source 权重（小权重，优先相关性）
            SOURCE_WEIGHT = {"user_confirmed": 2, "user_statement": 1}

            items: list[MemoryItem] = []
            for record in records:
                # 搜索范围：key + value + evidence
                evidence = record.evidence or ""
                search_text = f"{record.key} {record.value} {evidence}".lower()

                # 关键词命中
                hit_count = 0
                for kw in keywords:
                    if kw.lower() in search_text:
                        hit_count += 1

                # 无命中 → 不加入结果
                if hit_count == 0:
                    continue

                # 评分：相关性为主，source 为辅
                score = hit_count * 2
                score += SOURCE_WEIGHT.get(record.source, 0)

                # 时间加分：7 天内创建的记忆 +2
                from datetime import datetime, timezone, timedelta
                if record.created_at:
                    now = datetime.now()
                    if record.created_at.tzinfo is None:
                        record_dt = record.created_at.replace(tzinfo=None)
                    else:
                        record_dt = record.created_at.replace(tzinfo=timezone.utc).astimezone(None).replace(tzinfo=None)
                    if (now - record_dt) < timedelta(days=7):
                        score += 2

                items.append(
                    MemoryItem(
                        key=record.key,
                        value=record.value,
                        importance=record.importance + score,
                    )
                )

            # V3.5: 无命中 → 返回空，不 fallback 全量注入
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
