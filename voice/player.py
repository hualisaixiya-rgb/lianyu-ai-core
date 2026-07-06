"""音频播放模块。

基于 winsound（Windows）实现音频播放。
不依赖 pydub（避免 Python 3.13+ 的 audioop 兼容问题）。
"""

import subprocess
import platform
from pathlib import Path

from loguru import logger


def play_audio(filepath: str | Path) -> bool:
    """播放音频文件。

    支持 WAV（直接播放）和 MP3（调用系统播放器）。

    Args:
        filepath: 音频文件路径

    Returns:
        是否播放成功
    """
    filepath = Path(filepath)
    if not filepath.exists():
        logger.error(f"音频文件不存在: {filepath}")
        return False

    system = platform.system()
    suffix = filepath.suffix.lower()

    try:
        if system == "Windows":
            if suffix == ".wav":
                import winsound
                winsound.PlaySound(str(filepath), winsound.SND_FILENAME)
            else:
                # MP3 等格式：调用默认播放器
                import os
                os.startfile(str(filepath))
        elif system == "Darwin":
            subprocess.run(["afplay", str(filepath)], check=True)
        else:
            subprocess.run(["aplay", str(filepath)], check=True)

        logger.debug(f"播放完成: {filepath}")
        return True
    except Exception as e:
        logger.error(f"播放失败: {e}")
        return False
