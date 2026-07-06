"""Windows SAPI TTS 后端。

系统内置，零依赖，离线可用。
直接朗读，不生成文件。
"""

from pathlib import Path

from loguru import logger

from voice.tts.base import TTSBackend


class SAPITTSBackend(TTSBackend):
    """Windows SAPI TTS —— 系统内置语音。"""

    needs_playback = False

    def __init__(self) -> None:
        """初始化 SAPI TTS。"""
        logger.info("SAPI TTS 初始化")

    async def synthesize(self, text: str, output_path: str | Path) -> Path:
        """SAPI 直接朗读，不写文件。"""
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._speak, text)
        return Path(output_path)

    @staticmethod
    def _speak(text: str) -> None:
        """调用 Windows SAPI 朗读。"""
        try:
            import win32com.client

            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Speak(text)
            logger.debug(f"SAPI: {len(text)} 字")
        except ImportError:
            logger.error("SAPI 需要 pywin32: uv pip install pywin32")
            raise
        except Exception as e:
            logger.error(f"SAPI 失败: {e}")
            raise
