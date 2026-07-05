"""配置管理模块。

使用 Pydantic Settings 从环境变量和 .env 文件加载配置。
"""

from config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
