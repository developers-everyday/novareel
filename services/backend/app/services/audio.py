"""Audio processing pipeline — silence trim, normalize, speed adjust, ducking."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioProcessingError(Exception):
  """Raised when an audio processing step fails."""
  pass


class AudioProcessor:
  """Post-processing pipeline for narration audio.

  All operations are non-destructive: each step writes to a temp file
  and the final result is written back to the output path.
  """

  def __init__(self, ffmpeg_path: str | None = None):
    self._ffmpeg = ffmpeg_path or shutil.which('ffmpeg') or 'ffmpeg'
    self._ffprobe = shutil.which('ffprobe') or 'ffprobe'

  # ── Public API ──────────────────────────────────────────────────────────

  def process(
    self,
    input_path: Path,
    output_path: Path,
    *,
    trim_silence: bool = True,
    normalize: bool = True,
    speed: float = 1.0,
    silence_threshold_db: float = -40.0,
    silence_min_duration: float = 0.3,
    target_loudness_lufs: float = -16.0,
  ) -> Path:
    """Run the full audio processing pipeline.

    Args:
      input_path: Source MP3/audio file.
      output_path: Destination path for processed audio.
      trim_silence: Remove leading/trailing silence.
      normalize: Apply loudness normalization (EBU R128).
      speed: Playback speed multiplier (0.5–2.0). 1.0 = no change.
      silence_threshold_db: dB threshold for silence detection.
      silence_min_duration: Minimum silence duration (seconds) to trim.
      target_loudness_lufs: Target loudness in LUFS for normalization.

    Returns:
      Path to the processed audio file.
    """
    if not input_path.exists():
      raise AudioProcessingError(f'Input file not found: {input_path}')

    current = input_path
    temp_files: list[Path] = []

    try:
      if trim_silence:
        trimmed = self._make_temp('.mp3')
        temp_files.append(trimmed)
        if self._trim_silence(current, trimmed, silence_threshold_db, silence_min_duration):
          current = trimmed

      if speed != 1.0:
        sped = self._make_temp('.mp3')
        temp_files.append(sped)
        if self._adjust_speed(current, sped, speed):
          current = sped

      if normalize:
        normed = self._make_temp('.mp3')
        temp_files.append(normed)
        if self._normalize(current, normed, target_loudness_lufs):
          current = normed

      # Write final output
      if current != input_path:
        shutil.copy2(current, output_path)
      else:
        shutil.copy2(input_path, output_path)

      return output_path

    finally:
      for tmp in temp_files:
        tmp.unlink(missing_ok=True)

  def get_duration(self, audio_path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    cmd = [
      self._ffprobe,
      '-v', 'error',
      '-show_entries', 'format=duration',
      '-of', 'default=noprint_wrappers=1:nokey=1',
      str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
      logger.warning('ffprobe duration failed: %s', result.stderr.decode('utf-8', errors='replace')[-200:])
      return 0.0
    try:
      return float(result.stdout.decode().strip())
    except (ValueError, TypeError):
      return 0.0

  def duck_background(
    self,
    narration_path: Path,
    music_path: Path,
    output_path: Path,
    *,
    narration_volume: float = 1.0,
    music_volume: float = 0.12,
  ) -> Path:
    """Mix narration with background music, ducking the music volume.

    Args:
      narration_path: Path to the narration audio.
      music_path: Path to background music.
      output_path: Path for the mixed output.
      narration_volume: Volume multiplier for narration (1.0 = unchanged).
      music_volume: Volume multiplier for background music.

    Returns:
      Path to the mixed audio file.
    """
    cmd = [
      self._ffmpeg, '-y',
      '-i', str(narration_path),
      '-i', str(music_path),
      '-filter_complex',
      (
        f'[0:a]volume={narration_volume}[narr];'
        f'[1:a]aloop=loop=-1:size=2e+09,volume={music_volume}[bg];'
        f'[narr][bg]amix=inputs=2:duration=first[out]'
      ),
      '-map', '[out]',
      '-c:a', 'libmp3lame', '-q:a', '2',
      str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
      logger.warning('Audio ducking failed: %s', result.stderr.decode('utf-8', errors='replace')[-200:])
      shutil.copy2(narration_path, output_path)
    return output_path

  # ── Private helpers ─────────────────────────────────────────────────────

  @staticmethod
  def _make_temp(suffix: str = '.mp3') -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix='novareel-audio-')
    import os
    os.close(fd)
    return Path(path)

  def _trim_silence(
    self, input_path: Path, output_path: Path,
    threshold_db: float, min_duration: float,
  ) -> bool:
    """Remove leading and trailing silence using silenceremove filter."""
    af = (
      f'silenceremove=start_periods=1:start_threshold={threshold_db}dB'
      f':start_duration={min_duration}'
      f',areverse'
      f',silenceremove=start_periods=1:start_threshold={threshold_db}dB'
      f':start_duration={min_duration}'
      f',areverse'
    )
    return self._run_ffmpeg_af(input_path, output_path, af)

  def _adjust_speed(self, input_path: Path, output_path: Path, speed: float) -> bool:
    """Adjust playback speed using atempo filter (supports 0.5–2.0)."""
    speed = max(0.5, min(speed, 2.0))
    if abs(speed - 1.0) < 0.01:
      return False
    af = f'atempo={speed}'
    return self._run_ffmpeg_af(input_path, output_path, af)

  def _normalize(self, input_path: Path, output_path: Path, target_lufs: float) -> bool:
    """Apply EBU R128 loudness normalization using loudnorm filter."""
    af = (
      f'loudnorm=I={target_lufs}:TP=-1.5:LRA=11'
      f':print_format=summary'
    )
    return self._run_ffmpeg_af(input_path, output_path, af)

  def _run_ffmpeg_af(self, input_path: Path, output_path: Path, af: str) -> bool:
    """Run ffmpeg with an audio filter and return success status."""
    cmd = [
      self._ffmpeg, '-y',
      '-i', str(input_path),
      '-af', af,
      '-c:a', 'libmp3lame', '-q:a', '2',
      str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0:
      logger.warning('ffmpeg audio filter failed (%s): %s', af[:40], result.stderr.decode('utf-8', errors='replace')[-200:])
      return False
    return output_path.exists() and output_path.stat().st_size > 100
