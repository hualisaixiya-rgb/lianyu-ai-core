"""XTTS v2 后端。

Coqui XTTS v2 语音合成，支持 speaker_wav 音色克隆。
模型全局单例，整个程序生命周期只加载一次。

特性：
- GPU 优先（CUDA），自动降级 CPU
- 配置驱动参数（temperature / speed / language）
- 推理失败自动抛异常，由工厂函数降级到备用 TTS
"""

import asyncio
import time
from pathlib import Path

from loguru import logger

from voice.tts.base import TTSBackend

# ================================================================
# coqui-tts 兼容补丁 —— 注入新版 transformers 已删除的旧 API
# ================================================================
import torch
from transformers.utils import import_utils as _tf

# 缺失函数补丁列表
_patches = {
    "is_torch_greater_or_equal": lambda v, torch_version=None: torch.__version__ >= v,
    "isin_mps_friendly": lambda elements, test_elements, assume_unique=False, invert=False: torch.isin(elements, test_elements, assume_unique=assume_unique),
    "is_torchcodec_available": lambda: False,
    "is_torchaudio_available": lambda: True,
    "is_vision_available": lambda: False,
    "is_speech_available": lambda: False,
}

for _name, _impl in _patches.items():
    if not hasattr(_tf, _name):
        setattr(_tf, _name, _impl)

# 同时修复 transformers.pytorch_utils（TTS 深层导入用此路径）
from transformers import pytorch_utils as _tf_pt
for _name, _impl in _patches.items():
    if not hasattr(_tf_pt, _name):
        setattr(_tf_pt, _name, _impl)

# 全局模型单例
_xtts_model = None
_xtts_device = None


def _detect_device() -> str:
    """检测可用设备。

    Returns:
        "cuda" 或 "cpu"
    """
    try:
        import torch

        if torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
    except ImportError:
        device = "cpu"

    logger.info(f"XTTS 设备检测: {device}")
    return device


def _load_model(model_name: str) -> None:
    """加载 XTTS 模型（全局单例，只执行一次）。

    Args:
        model_name: 模型名称
    """
    global _xtts_model, _xtts_device

    if _xtts_model is not None:
        return

    _xtts_device = _detect_device()

    from TTS.api import TTS

    logger.info(f"加载 XTTS 模型: {model_name}（约 2GB，首次需下载）...")
    t0 = time.time()
    _xtts_model = TTS(model_name=model_name, progress_bar=False)
    # 移动到 GPU（如果可用）
    if _xtts_device == "cuda":
        _xtts_model.to("cuda")
    elapsed = time.time() - t0
    logger.info(f"XTTS 加载完成 | 耗时={elapsed:.1f}s | 设备={_xtts_device}")


class XTTSBackend(TTSBackend):
    """XTTS v2 语音合成后端。

    使用方式：
        backend = XTTSBackend(
            speaker_wav="voice/erii.wav",
            temperature=0.65,
            speed=1.0,
            language="zh-cn",
        )
        await backend.synthesize("你好", "output.wav")
    """

    def __init__(
        self,
        model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2",
        speaker_wav: str = "",
        language: str = "zh-cn",
        temperature: float = 0.65,
        speed: float = 1.0,
    ) -> None:
        """初始化 XTTS 后端。

        Args:
            model_name: XTTS 模型名称
            speaker_wav: 参考音频路径（音色克隆源）
            language: 合成语言
            temperature: 合成温度（0-1，越低越稳定）
            speed: 语速（1.0 正常，<1 慢，>1 快）
        """
        self.model_name = model_name
        self.speaker_wav = speaker_wav
        self.language = language
        self.temperature = temperature
        self.speed = speed

        logger.info(
            f"XTTS 配置 | speaker={speaker_wav or '默认'} | "
            f"temp={temperature} | speed={speed} | lang={language}"
        )

    async def synthesize(self, text: str, output_path: str | Path) -> Path:
        """合成语音。

        Args:
            text: 要合成的文本
            output_path: 输出 WAV 文件路径

        Returns:
            输出文件路径

        Raises:
            RuntimeError: 合成失败
        """
        global _xtts_model, _xtts_device

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 确保模型已加载
        _load_model(self.model_name)

        if _xtts_model is None:
            raise RuntimeError("XTTS 模型未加载")

        t0 = time.time()

        try:
            # 在线程池执行同步推理
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: _xtts_model.tts_to_file(
                    text=text,
                    speaker_wav=self.speaker_wav if self.speaker_wav else None,
                    file_path=str(output_path),
                    language=self.language,
                    temperature=self.temperature,
                    speed=self.speed,
                ),
            )
        except Exception as e:
            raise RuntimeError(f"XTTS 推理失败: {e}") from e

        elapsed = time.time() - t0
        logger.info(
            f"XTTS: {len(text)} 字 → {elapsed:.1f}s | "
            f"设备={_xtts_device or '?'}"
        )
        return output_path
