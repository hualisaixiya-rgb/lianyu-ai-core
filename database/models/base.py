"""SQLAlchemy 声明式基类。

所有 ORM 模型都必须继承此类。
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ORM 基类。

    提供统一的元数据管理，所有模型继承自此。
    """
    pass
