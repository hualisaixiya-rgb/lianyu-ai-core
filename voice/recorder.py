"""录音模块。

基于 sounddevice 实现麦克风录音。
支持固定时长录音和手动控制。
"""

import tempfile
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from loguru import logger


# 录音参数
DEFAULT_SAMPLE_RATE = 16000  # Whisper 推荐 16kHz
DEFAULT_DURATION = 5          # 默认录音时长（秒）
DEFAULT_CHANNELS = 1          # 单声道


class Recorder:
    """音频录制器。

    封装 sounddevice 的录音功能。

    使用方式：
        rec = Recorder()
        rec.record_to_file("input.wav", duration=5)
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
    ) -> None:
        """初始化录音器。

        Args:
            sample_rate: 采样率（Hz）
            channels: 声道数
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self._list_devices()
        logger.info(
            f"Recorder 初始化 | rate={sample_rate}Hz | channels={channels}"
        )

    def _list_devices(self) -> None:
        """列出可用音频设备（调试用）。"""
        try:
            devices = sd.query_devices()
            input_devices = [
                d for d in devices if d["max_input_channels"] > 0
            ]
            if input_devices:
                logger.debug(f"可用输入设备: {len(input_devices)} 个")
                for d in input_devices:
                    logger.debug(f"  - {d['name']}")
            else:
                logger.warning("未检测到音频输入设备")
        except Exception as e:
            logger.warning(f"无法列出音频设备: {e}")

    def record(self, duration: float = DEFAULT_DURATION) -> np.ndarray:
        """录制固定时长的音频。

        Args:
            duration: 录音时长（秒）

        Returns:
            numpy 数组（shape=(samples, channels)），float32 格式

        Raises:
            RuntimeError: 录音失败
        """
        if duration <= 0:
            raise ValueError("录音时长必须大于 0 秒")

        total_frames = int(self.sample_rate * duration)

        logger.info(f"开始录音 | 时长={duration}s")
        try:
            audio = sd.rec(
                total_frames,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
            )
            sd.wait()  # 等待录音完成
            logger.info(f"录音完成 | shape={audio.shape}")
            return audio
        except Exception as e:
            raise RuntimeError(f"录音失败: {e}") from e

    def record_to_file(
        self,
        filepath: str | Path,
        duration: float = DEFAULT_DURATION,
    ) -> Path:
        """录制音频并保存为 WAV 文件。

        Args:
            filepath: 输出文件路径
            duration: 录音时长（秒）

        Returns:
            保存的文件路径
        """
        audio = self.record(duration)
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        sf.write(str(filepath), audio, self.sample_rate)
        logger.info(f"音频已保存: {filepath}")
        return filepath

    def record_to_temp(self, duration: float = DEFAULT_DURATION) -> Path:
        """录制音频并保存到临时文件。

        Args:
            duration: 录音时长（秒）

        Returns:
            临时文件路径
        """
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        return self.record_to_file(tmp.name, duration)
