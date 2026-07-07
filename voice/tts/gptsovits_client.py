"""GPT-SoVITS HTTP 客户端。

通过 HTTP API 调用独立运行的 GPT-SoVITS 服务。
支持长文本自动拆句 + 音频拼接。
"""

import re
import tempfile
from pathlib import Path

import aiohttp
from loguru import logger
from pydub import AudioSegment

from voice.tts.base import TTSBackend


# 情绪 → 参考音频文件名映射
EMOTION_FILES = {
    "neutral": "speaker_neutral.wav",
    "happy": "speaker_happy.wav",
    "sad": "speaker_sad.wav",
    "calm": "speaker_calm.wav",
}

# 每句最大字数（超出则拆分）
MAX_CHARS_PER_SENTENCE = 30


class GPTSoVITSClient(TTSBackend):
    """GPT-SoVITS HTTP API 客户端。"""

    def __init__(
        self,
        base_url: str = "http://localhost:9880",
        speaker_dir: str = "voice/gptsovits",
        default_emotion: str = "neutral",
        timeout: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.speaker_dir = Path(speaker_dir)
        self.default_emotion = default_emotion
        self.timeout = timeout
        self._available = False
        self.speaker_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"GPT-SoVITS 客户端 | API={base_url} | speaker_dir={speaker_dir}"
        )

    async def synthesize(
        self,
        text: str,
        output_path: str | Path,
        emotion: str | None = None,
    ) -> Path:
        """合成语音。长文本自动拆句，逐句合成后拼接。

        Args:
            text: 要合成的文本
            output_path: 输出 WAV 文件路径
            emotion: 情绪标签

        Returns:
            输出文件路径
        """
        emotion = emotion or self.default_emotion
        ref_path = self._find_ref_audio(emotion)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # VSC 轻量预处理
        from voice.vsc import apply_style
        styled_text, styled_prompt = apply_style(text, "eri")

        # 拆分为短句
        sentences = _split_sentences(styled_text)

        if len(sentences) == 1:
            # 短文本直接合成
            return await self._synthesize_one(
                sentences[0], styled_prompt, ref_path, output_path
            )

        # 长文本逐句合成 + 拼接
        logger.info(f"长文本拆分为 {len(sentences)} 句，逐句合成...")
        segment_files = []
        for i, sent in enumerate(sentences):
            if not sent.strip():
                continue
            tmp_file = output_path.parent / f"_seg_{i:03d}.wav"
            try:
                await self._synthesize_one(
                    sent, styled_prompt, ref_path, tmp_file
                )
                segment_files.append(tmp_file)
            except Exception as e:
                logger.warning(f"第 {i} 句合成失败: {e}，跳过")
                # 插入短暂静音作为占位
                silence = AudioSegment.silent(duration=300)
                silence.export(tmp_file, format="wav")
                segment_files.append(tmp_file)

        # 拼接所有片段
        if segment_files:
            combined = AudioSegment.empty()
            for f in segment_files:
                combined += AudioSegment.from_wav(f) + AudioSegment.silent(duration=200)
            combined.export(output_path, format="wav")
            # 清理临时文件
            for f in segment_files:
                try:
                    f.unlink()
                except Exception:
                    pass

        logger.info(
            f"GPT-SoVITS: {len(text)}字, {len(sentences)}句 → {output_path}"
        )
        return output_path

    async def _synthesize_one(
        self,
        text: str,
        prompt_text: str,
        ref_path: Path,
        output_path: Path,
    ) -> Path:
        """合成单句。"""
        payload = {
            "text": text,
            "text_lang": "zh",
            "ref_audio_path": str(ref_path.resolve()),
            "prompt_text": prompt_text,
            "prompt_lang": "zh",
            "top_k": 12,
            "top_p": 0.75,
            "temperature": 0.65,
            "text_split_method": "cut0",
            "batch_size": 1,
            "speed_factor": 0.85,
            "seed": -1,
        }

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

        return output_path

    def _find_ref_audio(self, emotion: str) -> Path:
        """查找参考音频文件。"""
        ref_file = EMOTION_FILES.get(emotion, EMOTION_FILES["neutral"])
        ref_path = self.speaker_dir / ref_file

        if not ref_path.exists():
            available = list(self.speaker_dir.glob("*.wav"))
            if available:
                ref_path = available[0]
                logger.warning(f"参考音频 {ref_file} 不存在，使用 {ref_path.name}")
            else:
                raise RuntimeError(
                    f"参考音频目录为空: {self.speaker_dir}"
                )
        return ref_path


def _split_sentences(text: str) -> list[str]:
    """将文本按句号拆分为短句。……和、不作为分割点。

    Args:
        text: 输入文本

    Returns:
        短句列表（至少 1 句）
    """
    # 按句末标点拆分（……不是句末，是停顿）
    raw = re.split(r"(?<=[。！？!?])", text)

    result = []
    for part in raw:
        part = part.strip()
        if not part:
            continue
        # 过滤纯标点或无意义短句
        meaningful = re.sub(r"[……\s]+", "", part)
        if not meaningful or len(meaningful) < 2:
            continue
        # 超长句二次拆分
        if len(part) > MAX_CHARS_PER_SENTENCE:
            sub_parts = re.split(r"(?<=[，,])", part)
            for sp in sub_parts:
                sp = sp.strip()
                meaningful2 = re.sub(r"[……\s]+", "", sp)
                if meaningful2 and len(meaningful2) >= 2:
                    result.append(sp)
        else:
            result.append(part)

    # 如果拆分后为空，返回原文本
    if not result:
        result = [text.strip()]

    return result
