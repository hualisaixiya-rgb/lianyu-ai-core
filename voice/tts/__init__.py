"""TTS 工厂 —— 自动选择后端 + 降级链。

优先级：xtts → edge → sapi

用法：
    from voice.tts import create_tts
    tts = create_tts()                 # auto
    tts = create_tts(backend="xtts", speaker_wav="voice/erii.wav")
"""

from loguru import logger

from voice.tts.base import TTSBackend
from voice.tts.edge_tts import EdgeTTSBackend
from voice.tts.sapi import SAPITTSBackend
from voice.tts.xtts import XTTSBackend


def create_tts(backend: str = "auto", **kwargs) -> TTSBackend:
    """TTS 工厂函数 —— 自动降级。

    降级链：xtts → edge → sapi

    Args:
        backend: "auto" / "xtts" / "edge" / "sapi"
        **kwargs: 传递给具体后端的参数

    Returns:
        TTSBackend 实例

    Raises:
        RuntimeError: 所有后端都不可用
    """
    # 明确指定后端
    if backend == "xtts":
        return XTTSBackend(**kwargs)
    if backend == "edge":
        return EdgeTTSBackend(**kwargs)
    if backend == "sapi":
        return SAPITTSBackend()

    # auto: 读取配置或依次尝试
    from config.settings import get_settings
    settings = get_settings()
    provider = getattr(settings, "tts", None)
    if provider and provider.provider and provider.provider != "auto":
        backend = provider.provider

    # 构建降级链
    chain = [
        ("XTTS", lambda: _try_xtts(provider, **kwargs)),
        ("EdgeTTS", lambda: EdgeTTSBackend(**kwargs)),
        ("SAPI", lambda: SAPITTSBackend()),
    ]

    for name, factory in chain:
        try:
            instance = factory()
            logger.info(f"TTS 后端: {name}")
            return instance
        except Exception as e:
            logger.warning(f"TTS {name} 不可用: {e}")

    raise RuntimeError("所有 TTS 后端均不可用")


def _try_xtts(provider, **kwargs) -> XTTSBackend:
    """尝试创建 XTTS 后端（从配置读取参数）。"""
    xtts_kwargs = dict(kwargs)

    if provider:
        if not xtts_kwargs.get("speaker_wav") and provider.xtts_speaker_wav:
            xtts_kwargs["speaker_wav"] = provider.xtts_speaker_wav
        if not xtts_kwargs.get("language"):
            xtts_kwargs["language"] = provider.xtts_language
        if not xtts_kwargs.get("temperature"):
            xtts_kwargs["temperature"] = provider.xtts_temperature
        if not xtts_kwargs.get("speed"):
            xtts_kwargs["speed"] = provider.xtts_speed

    return XTTSBackend(**xtts_kwargs)
