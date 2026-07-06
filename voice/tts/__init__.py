"""TTS 工厂 —— 自动选择后端 + 降级链。

降级链：gptsovits → xtts → edge → sapi

用法：
    from voice.tts import create_tts
    tts = create_tts()                          # auto
    tts = create_tts(backend="gptsovits")       # GPT-SoVITS 音色克隆
    tts = create_tts(backend="edge")            # EdgeTTS
"""

from loguru import logger

from voice.tts.base import TTSBackend
from voice.tts.edge_tts import EdgeTTSBackend
from voice.tts.sapi import SAPITTSBackend


def create_tts(backend: str = "auto", **kwargs) -> TTSBackend:
    """TTS 工厂函数 —— 自动降级。

    降级链：gptsovits → xtts → edge → sapi

    Args:
        backend: "auto" / "gptsovits" / "xtts" / "edge" / "sapi"
        **kwargs: 传递给具体后端的参数

    Returns:
        TTSBackend 实例
    """
    # 明确指定后端
    if backend == "gptsovits":
        from voice.tts.gptsovits_client import GPTSoVITSClient
        return GPTSoVITSClient(**kwargs)
    if backend == "xtts":
        from voice.tts.xtts import XTTSBackend
        return XTTSBackend(**kwargs)
    if backend == "edge":
        return EdgeTTSBackend(**kwargs)
    if backend == "sapi":
        return SAPITTSBackend()

    # auto: 读配置
    from config.settings import get_settings
    settings = get_settings()
    provider = getattr(settings, "tts", None)

    # 构建降级链
    chain = []

    # GPT-SoVITS（如果配置了 URL）
    want_gptsovits = (
        (provider and provider.gptsovits_url) or
        kwargs.get("base_url")
    )
    if want_gptsovits:
        chain.append(("GPT-SoVITS", lambda: _try_gptsovits(provider, **kwargs)))

    # XTTS（如果配置了 speaker_wav）
    want_xtts = (
        (provider and provider.provider == "xtts") or
        kwargs.get("speaker_wav") or
        (provider and provider.xtts_speaker_wav)
    )
    if want_xtts:
        chain.append(("XTTS", lambda: _try_xtts(provider, **kwargs)))

    # EdgeTTS（默认保底）
    chain.append(("EdgeTTS", lambda: EdgeTTSBackend(**kwargs)))
    chain.append(("SAPI", lambda: SAPITTSBackend()))

    for name, factory in chain:
        try:
            instance = factory()
            logger.info(f"TTS 后端: {name}")
            return instance
        except Exception as e:
            logger.warning(f"TTS {name} 不可用: {e}")

    raise RuntimeError("所有 TTS 后端均不可用")


def _try_gptsovits(provider, **kwargs):
    """尝试创建 GPT-SoVITS 客户端。"""
    from voice.tts.gptsovits_client import GPTSoVITSClient
    gs_kwargs = {}
    if provider:
        if provider.gptsovits_url:
            gs_kwargs["base_url"] = provider.gptsovits_url
        if provider.gptsovits_speaker_dir:
            gs_kwargs["speaker_dir"] = provider.gptsovits_speaker_dir
    gs_kwargs.update(kwargs)
    return GPTSoVITSClient(**gs_kwargs)


def _try_xtts(provider, **kwargs):
    """尝试创建 XTTS 后端。"""
    from voice.tts.xtts import XTTSBackend
    xtts_kwargs = dict(kwargs)
    if provider:
        if not xtts_kwargs.get("speaker_wav") and provider.xtts_speaker_wav:
            xtts_kwargs["speaker_wav"] = provider.xtts_speaker_wav
        xtts_kwargs.setdefault("language", provider.xtts_language)
        xtts_kwargs.setdefault("temperature", provider.xtts_temperature)
        xtts_kwargs.setdefault("speed", provider.xtts_speed)

    try:
        import torchaudio  # noqa: F401
        from TTS.api import TTS  # noqa: F401
    except Exception as e:
        raise RuntimeError(f"XTTS 依赖不可用: {e}") from e

    return XTTSBackend(**xtts_kwargs)
