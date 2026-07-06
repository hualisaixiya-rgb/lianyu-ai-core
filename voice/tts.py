"""语音合成（TTS）模块。

支持两种后端：
- EdgeTTS: 免费、无需 API Key、音质好、轻量（默认）
- XTTS:   支持音色克隆（需要 pip install TTS + 下载模型，约 2GB）

通过工厂函数 create_tts() 根据配置选择后端。
"""

from abc import ABC, abstractmethod
from pathlib import Path

from loguru import logger


class TTSBackend(ABC):
    """TTS 后端抽象基类。"""

    @abstractmethod
    async def synthesize(self, text: str, output_path: str | Path) -> Path:
        """将文本合成语音并保存为文件。

        Args:
            text: 要合成的文本
            output_path: 输出音频文件路径（.wav 或 .mp3）

        Returns:
            输出文件路径
        """
        ...


class EdgeTTSBackend(TTSBackend):
    """基于 Edge TTS 的语音合成。

    使用微软 Edge 的免费 TTS 服务。
    支持多种中文语音。
    """

    # 推荐的中文语音
    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"  # 女声，自然

    def __init__(self, voice: str = DEFAULT_VOICE) -> None:
        """初始化 Edge TTS。

        Args:
            voice: 语音名称
        """
        self.voice = voice
        logger.info(f"EdgeTTS 初始化 | voice={voice}")

    async def synthesize(self, text: str, output_path: str | Path) -> Path:
        """合成语音。

        Args:
            text: 文本
            output_path: 输出路径（.mp3）

        Returns:
            输出文件路径
        """
        import edge_tts

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(str(output_path))

        logger.debug(f"TTS 完成: {output_path} ({len(text)} 字)")
        return output_path


class XTTSBackend(TTSBackend):
    """基于 XTTS v2 的语音合成。

    支持 speaker_wav 音色克隆。
    需要: pip install TTS
    首次运行下载模型（约 2GB）。
    """

    def __init__(
        self,
        model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2",
        speaker_wav: str | Path | None = None,
    ) -> None:
        """初始化 XTTS。

        Args:
            model_name: 模型名称
            speaker_wav: 参考音频（用于音色克隆），为 None 则使用默认音色
        """
        self.model_name = model_name
        self.speaker_wav = str(speaker_wav) if speaker_wav else None
        self._model = None
        logger.info(f"XTTS 初始化 | model={model_name}")

    @property
    def model(self):
        """延迟加载 XTTS 模型。"""
        if self._model is None:
            from TTS.api import TTS

            logger.info(f"加载 XTTS 模型: {self.model_name}（首次可能需下载 2GB）...")
            self._model = TTS(model_name=self.model_name, progress_bar=False)
            logger.info("XTTS 模型加载完成")
        return self._model

    async def synthesize(self, text: str, output_path: str | Path) -> Path:
        """合成语音（使用音色克隆）。

        Args:
            text: 文本
            output_path: 输出路径（.wav）

        Returns:
            输出文件路径
        """
        import asyncio

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # XTTS 的 tts_to_file 是同步的，用线程池执行
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self.model.tts_to_file(
                text=text,
                speaker_wav=self.speaker_wav,
                file_path=str(output_path),
                language="zh-cn",
            ),
        )

        logger.debug(f"XTTS 完成: {output_path} ({len(text)} 字)")
        return output_path


def create_tts(backend: str = "edge", **kwargs) -> TTSBackend:
    """TTS 工厂函数。

    Args:
        backend: "edge" 或 "xtts"
        **kwargs: 传递给具体后端的参数

    Returns:
        TTSBackend 实例
    """
    if backend == "xtts":
        return XTTSBackend(**kwargs)
    return EdgeTTSBackend(**kwargs)
