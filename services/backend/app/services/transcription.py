"""Word-level transcription backends for caption timing.

Supports:
  - AWS Transcribe (default for production)
  - OpenAI Whisper (local fallback)
  - Mock backend (for testing)

Each backend returns a list of WordTiming objects with word-level start/end times.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class WordTiming:
    """A single word with its timing in the audio."""
    word: str
    start_sec: float
    end_sec: float
    confidence: float = 1.0


class TranscriptionBackend(ABC):
    """Abstract base for transcription backends."""

    @abstractmethod
    def transcribe(self, audio_path: Path, language: str = 'en') -> list[WordTiming]:
        """Transcribe audio and return word-level timings."""
        ...


class MockTranscriptionBackend(TranscriptionBackend):
    """Mock backend for testing — generates evenly-spaced word timings from script lines."""

    def __init__(self, script_lines: list[str] | None = None):
        self._script_lines = script_lines or []

    def transcribe(self, audio_path: Path, language: str = 'en') -> list[WordTiming]:
        all_words: list[str] = []
        for line in self._script_lines:
            all_words.extend(line.split())

        if not all_words:
            all_words = ['Mock', 'transcription', 'output']

        # Distribute words evenly across a 30-second duration
        duration = 30.0
        word_duration = duration / len(all_words)
        timings: list[WordTiming] = []
        for i, word in enumerate(all_words):
            timings.append(WordTiming(
                word=word,
                start_sec=round(i * word_duration, 3),
                end_sec=round((i + 1) * word_duration, 3),
                confidence=0.99,
            ))
        return timings


class WhisperTranscriptionBackend(TranscriptionBackend):
    """Local Whisper transcription using openai-whisper package."""

    def __init__(self, model_name: str = 'base'):
        self._model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                import whisper
                self._model = whisper.load_model(self._model_name)
                logger.info('Loaded Whisper model: %s', self._model_name)
            except ImportError:
                raise RuntimeError(
                    'openai-whisper package not installed. '
                    'Install with: pip install openai-whisper'
                )
        return self._model

    def transcribe(self, audio_path: Path, language: str = 'en') -> list[WordTiming]:
        model = self._load_model()
        result = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
        )

        timings: list[WordTiming] = []
        for segment in result.get('segments', []):
            for word_info in segment.get('words', []):
                timings.append(WordTiming(
                    word=word_info['word'].strip(),
                    start_sec=round(word_info['start'], 3),
                    end_sec=round(word_info['end'], 3),
                    confidence=round(word_info.get('probability', 0.9), 3),
                ))
        return timings


class AWSTranscribeBackend(TranscriptionBackend):
    """AWS Transcribe backend — uploads audio to S3, starts transcription job, polls for results."""

    def __init__(self, *, region: str, s3_bucket: str, s3_prefix: str = 'transcriptions/'):
        self._region = region
        self._s3_bucket = s3_bucket
        self._s3_prefix = s3_prefix

    def transcribe(self, audio_path: Path, language: str = 'en') -> list[WordTiming]:
        import boto3

        s3 = boto3.client('s3', region_name=self._region)
        transcribe = boto3.client('transcribe', region_name=self._region)

        # Upload audio to S3
        job_name = f'novareel-{int(time.time()*1000)}'
        s3_key = f'{self._s3_prefix}{job_name}.mp3'
        s3.upload_file(str(audio_path), self._s3_bucket, s3_key)

        media_uri = f's3://{self._s3_bucket}/{s3_key}'

        # Map language codes
        lang_code = self._language_code(language)

        # Start transcription job
        transcribe.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': media_uri},
            MediaFormat='mp3',
            LanguageCode=lang_code,
            Settings={'ShowSpeakerLabels': False},
        )

        # Poll for completion
        for _ in range(120):  # 10 minutes max
            status = transcribe.get_transcription_job(TranscriptionJobName=job_name)
            job_status = status['TranscriptionJob']['TranscriptionJobStatus']
            if job_status == 'COMPLETED':
                break
            if job_status == 'FAILED':
                raise RuntimeError(f'Transcription job failed: {status}')
            time.sleep(5)

        # Get results
        transcript_uri = status['TranscriptionJob']['Transcript']['TranscriptFileUri']
        import urllib.request
        with urllib.request.urlopen(transcript_uri) as resp:
            result = json.loads(resp.read())

        # Parse word timings
        timings: list[WordTiming] = []
        items = result.get('results', {}).get('items', [])
        for item in items:
            if item['type'] == 'pronunciation':
                timings.append(WordTiming(
                    word=item['alternatives'][0]['content'],
                    start_sec=round(float(item['start_time']), 3),
                    end_sec=round(float(item['end_time']), 3),
                    confidence=round(float(item['alternatives'][0].get('confidence', '0.9')), 3),
                ))

        # Cleanup S3
        try:
            s3.delete_object(Bucket=self._s3_bucket, Key=s3_key)
            transcribe.delete_transcription_job(TranscriptionJobName=job_name)
        except Exception:
            logger.warning('Failed to cleanup transcription artifacts')

        return timings

    @staticmethod
    def _language_code(lang: str) -> str:
        """Map ISO 639-1 codes to AWS Transcribe language codes."""
        mapping = {
            'en': 'en-US', 'es': 'es-ES', 'fr': 'fr-FR', 'de': 'de-DE',
            'it': 'it-IT', 'pt': 'pt-BR', 'ja': 'ja-JP', 'ko': 'ko-KR',
            'zh': 'zh-CN', 'ar': 'ar-SA', 'hi': 'hi-IN', 'ru': 'ru-RU',
            'tr': 'tr-TR', 'nl': 'nl-NL', 'pl': 'pl-PL', 'sv': 'sv-SE',
            'th': 'th-TH', 'vi': 'vi-VN', 'id': 'id-ID', 'ms': 'ms-MY',
        }
        return mapping.get(lang, 'en-US')


# ── ASS Subtitle Generation ────────────────────────────────────────────────

def generate_ass_subtitles(
    word_timings: list[WordTiming],
    caption_style: str = 'word_highlight',
    resolution: str = '1920x1080',
) -> str:
    """Generate an ASS subtitle file from word timings.

    Styles:
      - word_highlight: Each word highlights as it's spoken (karaoke-like)
      - karaoke: Full karaoke with color sweep
      - simple: Standard word-by-word display
    """
    width, height = resolution.split('x')
    play_res_x, play_res_y = int(width), int(height)

    # Group words into subtitle lines (~5-8 words each)
    lines = _group_words_into_lines(word_timings)

    header = f"""[Script Info]
Title: NovaReel Captions
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,48,&H00FFFFFF,&H000088FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,60,1
Style: Highlight,Arial,48,&H000088FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: list[str] = []

    for line_words in lines:
        if not line_words:
            continue

        line_start = line_words[0].start_sec
        line_end = line_words[-1].end_sec

        if caption_style == 'karaoke':
            # Karaoke: use \kf tags for progressive highlight
            text_parts: list[str] = []
            for w in line_words:
                # Duration in centiseconds
                dur_cs = int(round((w.end_sec - w.start_sec) * 100))
                text_parts.append(f'{{\\kf{dur_cs}}}{w.word}')
            text = ' '.join(text_parts)
            events.append(
                f"Dialogue: 0,{_ass_time(line_start)},{_ass_time(line_end)},Default,,0,0,0,,{text}"
            )

        elif caption_style == 'word_highlight':
            # Word highlight: show all words but override color for the active word
            full_text = ' '.join(w.word for w in line_words)
            # Show the full line
            events.append(
                f"Dialogue: 0,{_ass_time(line_start)},{_ass_time(line_end)},Default,,0,0,0,,{full_text}"
            )
            # Overlay highlight for each word
            for w in line_words:
                events.append(
                    f"Dialogue: 1,{_ass_time(w.start_sec)},{_ass_time(w.end_sec)},Highlight,,0,0,0,,"
                    f"{{\\an2\\pos({play_res_x // 2},{play_res_y - 60})}}{w.word}"
                )

        else:  # simple
            text = ' '.join(w.word for w in line_words)
            events.append(
                f"Dialogue: 0,{_ass_time(line_start)},{_ass_time(line_end)},Default,,0,0,0,,{text}"
            )

    return header + '\n'.join(events) + '\n'


def _group_words_into_lines(
    word_timings: list[WordTiming], max_words: int = 7, max_gap_sec: float = 1.0,
) -> list[list[WordTiming]]:
    """Group words into subtitle lines based on count and timing gaps."""
    if not word_timings:
        return []

    lines: list[list[WordTiming]] = []
    current_line: list[WordTiming] = [word_timings[0]]

    for w in word_timings[1:]:
        prev = current_line[-1]
        gap = w.start_sec - prev.end_sec
        if len(current_line) >= max_words or gap > max_gap_sec:
            lines.append(current_line)
            current_line = [w]
        else:
            current_line.append(w)

    if current_line:
        lines.append(current_line)

    return lines


def _ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    return f'{h}:{m:02}:{s:02}.{cs:02}'


# ── Factory ────────────────────────────────────────────────────────────────

def build_transcription_backend(
    backend: str, settings, script_lines: list[str] | None = None,
) -> TranscriptionBackend:
    """Build a transcription backend from settings."""
    if settings.use_mock_ai:
        return MockTranscriptionBackend(script_lines=script_lines)

    if backend == 'whisper':
        model_name = getattr(settings, 'whisper_model', 'base')
        return WhisperTranscriptionBackend(model_name=model_name)

    if backend == 'aws_transcribe':
        return AWSTranscribeBackend(
            region=settings.aws_region,
            s3_bucket=settings.s3_bucket_name,
        )

    # Default to mock
    return MockTranscriptionBackend(script_lines=script_lines)
