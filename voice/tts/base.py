"""TTS 后端抽象基类。

所有 TTS 后端必须实现此接口。
"""

from abc import ABC, abstractmethod
from pathlib import Path


class TTSBackend(ABC):
    """TTS 后端抽象基类。"""

    # 是否需要外部播放器播放文件（SAPI 自己播放，不需要）
    needs_playback: bool = True

    @abstractmethod
    async def synthesize(self, text: str, output_path: str | Path) -> Path:
        """将文本合成语音并保存为文件。

        Args:
            text: 要合成的文本
            output_path: 输出音频文件路径

        Returns:
            输出文件路径
        """
        ...
