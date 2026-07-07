"""语音识别（STT）模块。

基于 faster-whisper 实现。
首次运行自动下载模型（~140MB for "small"）。
"""

from pathlib import Path

from loguru import logger


class WhisperSTT:
    """Whisper 语音识别器。

    封装 faster-whisper，提供简单的 transcribe 接口。

    使用方式：
        stt = WhisperSTT()
        text = stt.transcribe("audio.wav")
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        """初始化 Whisper 模型。

        Args:
            model_size: 模型大小，可选 tiny/base/small/medium/large
                       推荐 small（平衡速度与精度）
            device: 运行设备 cpu / cuda
            compute_type: 计算精度 int8（CPU）/ float16（GPU）
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None
        logger.info(
            f"WhisperSTT 初始化 | model={model_size} | "
            f"device={device} | precision={compute_type}"
        )

    @property
    def model(self):
        """延迟加载模型（首次调用时下载）。"""
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info(f"加载 Whisper 模型: {self.model_size}（首次可能需下载）...")
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            logger.info("Whisper 模型加载完成")
        return self._model

    def transcribe(self, audio_path: str | Path) -> str:
        """将音频文件转写为文本。

        Args:
            audio_path: WAV 音频文件路径

        Returns:
            识别出的文本。失败返回空字符串。
        """
        audio_path = Path(audio_path)
        if not audio_path.exists():
            logger.error(f"音频文件不存在: {audio_path}")
            return ""

        try:
            result = self.model.transcribe(
                str(audio_path),
                beam_size=5,
                language="zh",
            )

            if result is None:
                logger.error("STT 返回空（模型可能未就绪）")
                return ""

            segments, info = result

            if segments is None:
                logger.error("STT segments 为空（音频可能无声）")
                return ""

            # 拼接所有片段
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            text = "".join(text_parts)
            if not text:
                logger.warning("STT 未识别到文字")
                return ""
            logger.info(f"STT 结果 ({len(text)} 字): {text[:80]}...")
            return text

        except Exception as e:
            logger.error(f"语音识别失败: {e}")
            return ""
