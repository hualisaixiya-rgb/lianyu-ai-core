"""应用配置定义。

所有配置项都通过环境变量读取，支持 .env 文件。
命名规范：按模块分组，使用下划线分隔。

注意：使用 python-dotenv 在模块初始化时加载 .env 文件，
确保所有 pydantic-settings 子模型都能读取到环境变量。
"""

from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 在模块加载时读取 .env 文件，将变量注入 os.environ
# 确保后续所有 Settings 子类都能访问到环境变量
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)
else:
    # 尝试从当前工作目录加载
    load_dotenv(override=False)


class AISettings(BaseSettings):
    """AI / LLM 相关配置。"""

    model_config = SettingsConfigDict(env_prefix="AI_LLM_")

    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-chat"
    max_tokens: int = 4096
    temperature: float = 0.7


class TelegramSettings(BaseSettings):
    """Telegram Bot 配置。"""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: str = ""
    proxy: str = ""
    """HTTP 代理地址，如 http://127.0.0.1:7890。留空则不使用代理。"""


class DatabaseSettings(BaseSettings):
    """数据库配置。"""

    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    url: str = "sqlite+aiosqlite:///data/lianyu.db"


class AppSettings(BaseSettings):
    """应用基础配置。"""

    model_config = SettingsConfigDict(env_prefix="APP_")

    debug: bool = False
    log_level: str = "INFO"


class CharacterSettings(BaseSettings):
    """角色配置。"""

    model_config = SettingsConfigDict(env_prefix="CHARACTER_")

    name: str = "eryi"
    """当前加载的角色名，对应 character/characters/ 目录下的 YAML 文件名。"""


class TTSSettings(BaseSettings):
    """TTS 语音合成配置。"""

    model_config = SettingsConfigDict(env_prefix="TTS_")

    provider: str = "auto"
    """TTS 后端: auto / xtts / edge / sapi"""

    xtts_speaker_wav: str = ""
    """XTTS 参考音频路径（音色克隆源）"""

    xtts_language: str = "zh-cn"
    """XTTS 合成语言"""

    xtts_temperature: float = 0.65
    """XTTS 合成温度 (0-1)"""

    xtts_speed: float = 1.0
    """XTTS 语速 (1.0 正常, <1 慢, >1 快)"""

    gptsovits_url: str = ""
    """GPT-SoVITS API 地址，如 http://localhost:9880"""

    gptsovits_speaker_dir: str = "voice/gptsovits"
    """GPT-SoVITS 参考音频目录（含不同情绪的 wav）"""


class Settings(BaseSettings):
    """全局配置聚合类。

    使用方式：
        settings = get_settings()
        print(settings.ai.model)
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

    ai: AISettings = AISettings()
    telegram: TelegramSettings = TelegramSettings()
    database: DatabaseSettings = DatabaseSettings()
    app: AppSettings = AppSettings()
    character: CharacterSettings = CharacterSettings()
    tts: TTSSettings = TTSSettings()


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例。

    使用 lru_cache 确保整个应用生命周期内只加载一次配置。
    """
    return Settings()
