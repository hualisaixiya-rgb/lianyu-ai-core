"""Edge TTS 后端。

使用微软 Edge 的免费 TTS 服务，无需 API Key。
支持多种中文语音。
"""

from pathlib import Path

from loguru import logger

from voice.tts.base import TTSBackend


class EdgeTTSBackend(TTSBackend):
    """基于 Edge TTS 的语音合成。"""

    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

    def __init__(self, voice: str = DEFAULT_VOICE) -> None:
        """初始化 Edge TTS。"""
        self.voice = voice
        logger.info(f"EdgeTTS 初始化 | voice={voice}")

    async def synthesize(self, text: str, output_path: str | Path) -> Path:
        """合成语音，输出 MP3 文件。"""
        import edge_tts

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(str(output_path))

        logger.debug(f"EdgeTTS: {len(text)} 字 → {output_path}")
        return output_path
