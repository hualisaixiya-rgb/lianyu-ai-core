"""测试配置模块。"""

import os

from config.settings import AISettings, AppSettings, CharacterSettings, Settings


class TestSettings:
    """测试全局配置。"""

    def test_settings_structure(self):
        """测试 Settings 聚合结构完整。"""
        settings = Settings()
        # 验证所有子模块都被创建
        assert settings.ai is not None
        assert settings.telegram is not None
        assert settings.database is not None
        assert settings.app is not None
        assert settings.character is not None
        # 验证子模块类型正确
        assert isinstance(settings.ai, AISettings)
        assert isinstance(settings.app, AppSettings)
        assert isinstance(settings.character, CharacterSettings)

    def test_ai_settings_defaults(self):
        """测试 AI 配置的默认值（不读取 .env）。"""
        # 临时清除环境变量中的 AI_LLM_ 前缀变量，测试纯默认值
        old_keys = {k: os.environ.pop(k) for k in os.environ if k.startswith("AI_LLM_")}
        try:
            ai = AISettings()
            assert ai.model == "deepseek-chat"
            assert ai.max_tokens == 4096
            assert ai.temperature == 0.7
            assert ai.base_url == "https://api.deepseek.com"
        finally:
            os.environ.update(old_keys)

    def test_app_settings_fields(self):
        """测试 AppSettings 字段存在且类型正确。"""
        app = AppSettings()
        assert isinstance(app.debug, bool)
        assert isinstance(app.log_level, str)
        assert app.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
