"""测试配置和共享固件。

提供所有测试可复用的 fixture。
"""

import pytest


@pytest.fixture
def sample_settings():
    """提供测试用的配置实例。"""
    from config.settings import Settings
    return Settings()
