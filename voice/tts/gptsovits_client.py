"""GPT-SoVITS HTTP 客户端。

通过 HTTP API 调用独立运行的 GPT-SoVITS 服务。
GPT-SoVITS 运行在独立 conda 环境中，不影响当前 .venv。

用法:
    client = GPTSoVITSClient(base_url="http://localhost:9880")
    await client.synthesize("你好", "data/output.wav", emotion="calm")

情绪控制: 不同情绪使用不同的参考音频文件
    - neutral: 默认参考音频
    - happy / sad / calm: 对应情绪的参考音频
"""

from pathlib import Path

import aiohttp
from loguru import logger

from voice.tts.base import TTSBackend


# 情绪 → 参考音频文件名映射
EMOTION_FILES = {
    "neutral": "speaker_neutral.wav",
    "happy": "speaker_happy.wav",
    "sad": "speaker_sad.wav",
    "calm": "speaker_calm.wav",
}


class GPTSoVITSClient(TTSBackend):
    """GPT-SoVITS HTTP API 客户端。

    连接独立部署的 GPT-SoVITS API 服务，实现音色克隆 + 情绪 TTS。
    服务不可用时自动抛异常，由工厂函数降级到 EdgeTTS。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:9880",
        speaker_dir: str = "voice/gptsovits",
        default_emotion: str = "neutral",
        timeout: float = 30.0,
    ) -> None:
        """初始化 GPT-SoVITS 客户端。

        Args:
            base_url: GPT-SoVITS API 地址
            speaker_dir: 参考音频目录（含不同情绪的 wav）
            default_emotion: 默认情绪
            timeout: HTTP 超时秒数
        """
        self.base_url = base_url.rstrip("/")
        self.speaker_dir = Path(speaker_dir)
        self.default_emotion = default_emotion
        self.timeout = timeout
        self._available = False

        # 确保参考音频目录存在
        self.speaker_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"GPT-SoVITS 客户端初始化 | API={base_url} | "
            f"speaker_dir={speaker_dir}"
        )

    async def _check_health(self) -> bool:
        """检测 GPT-SoVITS 服务是否可用。"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def synthesize(
        self,
        text: str,
        output_path: str | Path,
        emotion: str | None = None,
    ) -> Path:
        """合成语音。

        Args:
            text: 要合成的文本
            output_path: 输出 WAV 文件路径
            emotion: 情绪标签（neutral/happy/sad/calm）

        Returns:
            输出文件路径

        Raises:
            RuntimeError: 服务不可用或合成失败
        """
        if not self._available:
            if not await self._check_health():
                raise RuntimeError(f"GPT-SoVITS 服务不可达: {self.base_url}")
            self._available = True

        emotion = emotion or self.default_emotion
        ref_file = EMOTION_FILES.get(emotion, EMOTION_FILES["neutral"])
        ref_path = self.speaker_dir / ref_file

        if not ref_path.exists():
            # 回退到任意可用参考文件
            available = list(self.speaker_dir.glob("*.wav"))
            if available:
                ref_path = available[0]
                logger.warning(
                    f"参考音频 {ref_file} 不存在，使用 {ref_path.name}"
                )
            else:
                raise RuntimeError(
                    f"参考音频目录为空: {self.speaker_dir}\n"
                    f"请放入参考音频文件（如 speaker_neutral.wav）"
                )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": str(ref_path.resolve()),
            "prompt_text": "",  # GPT-SoVITS v2 可为空
            "prompt_lang": "zh",
            "top_k": 5,
            "top_p": 0.8,
            "temperature": 0.8,
            "text_split_method": "cut0",
            "batch_size": 1,
            "speed_factor": 1.0,
            "seed": -1,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/tts",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status != 200:
                        detail = await resp.text()
                        raise RuntimeError(f"GPT-SoVITS API 错误: {detail}")

                    audio_bytes = await resp.read()
                    output_path.write_bytes(audio_bytes)

            logger.info(
                f"GPT-SoVITS: {len(text)}字 → {output_path} "
                f"[情绪={emotion}]"
            )
            return output_path

        except aiohttp.ClientError as e:
            self._available = False
            raise RuntimeError(f"GPT-SoVITS 连接失败: {e}") from e
