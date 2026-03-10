"""Editing plan compiler — converts an EditingPlan into FFmpeg commands and executes them.

The compiler walks the plan's steps in order:
1. Render each segment (image / video / color) into individual clip files.
2. Join segments using xfade transitions or simple concat.
3. Stitch intro / outro clips.
4. Apply post-processing steps (text overlays, logo, subtitles, audio, music, thumbnail).

The compiler is stateless — all intermediate files live in a caller-supplied temp directory.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from app.services.editing.schema import (
    AudioMuxParams,
    ColorSegmentParams,
    EditingPlan,
    ImageSegmentParams,
    IntroClipParams,
    LogoOverlayParams,
    MusicMixParams,
    OutroClipParams,
    SubtitleBurnParams,
    TextOverlayParams,
    ThumbnailParams,
    TransitionParams,
    VideoSegmentParams,
    ZoomDirection,
)

logger = logging.getLogger(__name__)


class CompilationResult:
    """Result of compiling and executing an editing plan."""

    def __init__(self) -> None:
        self.video_path: Path | None = None
        self.thumbnail_path: Path | None = None
        self.duration_sec: float = 0.0
        self.resolution: str = ''
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def success(self) -> bool:
        return self.video_path is not None and self.video_path.exists()


class PlanCompiler:
    """Compile an EditingPlan into a rendered video file."""

    def __init__(self, ffmpeg_path: str | None = None) -> None:
        self._ffmpeg = ffmpeg_path or shutil.which('ffmpeg') or 'ffmpeg'
        self._features: dict[str, bool] | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    def compile(self, plan: EditingPlan, work_dir: Path) -> CompilationResult:
        """Execute the full editing plan and return the result.

        Args:
            plan: The editing plan to compile.
            work_dir: Temporary directory for intermediate files.

        Returns:
            CompilationResult with paths to the output video and thumbnail.
        """
        result = CompilationResult()
        result.resolution = plan.resolution
        features = self._detect_features()

        width, height = plan.resolution.split('x')
        w, h = int(width), int(height)

        # ── Phase 1: Render segments ───────────────────────────────────────
        segments = plan.segment_steps
        if not segments:
            result.errors.append('No segment steps in editing plan')
            return result

        seg_paths: list[Path] = []
        seg_durations: list[float] = []

        for seg in segments:
            seg_file = work_dir / f'seg_{seg.order:03d}.mp4'

            if isinstance(seg, ImageSegmentParams):
                ok = self._render_image_segment(seg, seg_file, w, h, plan.ffmpeg_preset, features)
            elif isinstance(seg, VideoSegmentParams):
                ok = self._render_video_segment(seg, seg_file, w, h, plan.ffmpeg_preset, features)
            elif isinstance(seg, ColorSegmentParams):
                ok = self._render_color_segment(seg, seg_file, plan.resolution, plan.ffmpeg_preset)
            else:
                result.warnings.append(f'Unknown segment type: {type(seg).__name__}')
                continue

            if ok and seg_file.exists():
                seg_paths.append(seg_file)
                seg_durations.append(seg.duration_sec)
            else:
                result.warnings.append(f'Segment {seg.order} failed to render, using color fallback')
                fallback = work_dir / f'seg_{seg.order:03d}_fb.mp4'
                self._render_color_fallback(fallback, plan.resolution, seg.duration_sec, plan.ffmpeg_preset)
                if fallback.exists():
                    seg_paths.append(fallback)
                    seg_durations.append(seg.duration_sec)

        if not seg_paths:
            result.errors.append('All segments failed to render')
            return result

        # ── Phase 2: Join segments ─────────────────────────────────────────
        transition = plan.transition_step
        use_xfade = (
            features.get('xfade', False)
            and transition is not None
            and transition.duration_sec > 0
            and len(seg_paths) > 1
        )

        if use_xfade:
            joined = self._join_xfade(
                work_dir, seg_paths, seg_durations,
                transition.effect, transition.duration_sec, plan.ffmpeg_preset,
            )
            if joined is None:
                joined = self._join_concat(work_dir, seg_paths)
        else:
            joined = self._join_concat(work_dir, seg_paths)

        if joined is None or not joined.exists():
            result.errors.append('Segment join failed')
            return result

        current_video = joined
        total_duration = sum(seg_durations)

        # ── Phase 3: Intro / outro stitching ───────────────────────────────
        intro_steps = [s for s in plan.steps if isinstance(s, IntroClipParams)]
        outro_steps = [s for s in plan.steps if isinstance(s, OutroClipParams)]
        if intro_steps or outro_steps:
            stitched = self._stitch_intro_outro(
                work_dir, current_video,
                intro_steps[0] if intro_steps else None,
                outro_steps[0] if outro_steps else None,
            )
            if stitched and stitched.exists():
                current_video = stitched

        # ── Phase 4: Post-processing steps (in list order) ────────────────
        for step in plan.post_steps:
            if isinstance(step, TextOverlayParams):
                out = self._apply_text_overlay(
                    work_dir, current_video, step, features,
                    total_duration, plan.ffmpeg_preset,
                )
                if out:
                    current_video = out

            elif isinstance(step, LogoOverlayParams):
                out = self._apply_logo_overlay(
                    work_dir, current_video, step, w, h, plan.ffmpeg_preset,
                )
                if out:
                    current_video = out

            elif isinstance(step, SubtitleBurnParams):
                out = self._burn_subtitles(
                    work_dir, current_video, step, features, plan.ffmpeg_preset,
                )
                if out:
                    current_video = out

            elif isinstance(step, AudioMuxParams):
                out = self._mux_audio(work_dir, current_video, step)
                if out:
                    current_video = out

            elif isinstance(step, MusicMixParams):
                out = self._mix_music(work_dir, current_video, step)
                if out:
                    current_video = out

            elif isinstance(step, ThumbnailParams):
                thumb = self._extract_thumbnail(work_dir, current_video, step)
                if thumb:
                    result.thumbnail_path = thumb

            # IntroClipParams / OutroClipParams handled in Phase 3
            # TransitionParams handled in Phase 2

        result.video_path = current_video
        result.duration_sec = total_duration
        return result

    # ── Segment renderers ──────────────────────────────────────────────────

    def _render_image_segment(
        self, seg: ImageSegmentParams, output: Path,
        w: int, h: int, preset: str, features: dict[str, bool],
    ) -> bool:
        src = Path(seg.image_path)
        if not src.exists():
            return False

        total_frames = int(seg.fps * seg.duration_sec)

        if seg.zoom == ZoomDirection.ZOOM_IN:
            zoom_expr = f'min(zoom+{seg.zoom_speed},{seg.max_zoom})'
        else:
            zoom_expr = f"if(eq(on\\,1)\\,{seg.max_zoom}\\,max(zoom-{seg.zoom_speed}\\,1.0))"

        vf = (
            f'scale=8000:-1,'
            f"zoompan=z='{zoom_expr}':d={total_frames}:s={w}x{h}:fps={seg.fps},"
            f'setsar=1'
        )

        if seg.caption_text and features.get('drawtext', False):
            escaped = seg.caption_text.replace("'", "\u2019").replace(":", "\\:")
            vf += (
                f",drawtext=text='{escaped}'"
                f":fontsize=36:fontcolor=white:borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=h-80"
            )

        cmd = [
            self._ffmpeg, '-y',
            '-i', str(src),
            '-vf', vf,
            '-t', str(seg.duration_sec),
            '-c:v', 'libx264', '-preset', preset,
            '-pix_fmt', 'yuv420p', '-r', str(seg.fps),
            str(output),
        ]
        return self._run(cmd, f'image segment {seg.order}')

    def _render_video_segment(
        self, seg: VideoSegmentParams, output: Path,
        w: int, h: int, preset: str, features: dict[str, bool],
    ) -> bool:
        src = Path(seg.video_path)
        if not src.exists():
            return False

        vf = (
            f'scale={w}:{h}:force_original_aspect_ratio=decrease,'
            f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1'
        )

        if seg.caption_text and features.get('drawtext', False):
            escaped = seg.caption_text.replace("'", "\u2019").replace(":", "\\:")
            vf += (
                f",drawtext=text='{escaped}'"
                f":fontsize=36:fontcolor=white:borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=h-80"
            )

        cmd = [
            self._ffmpeg, '-y',
            '-i', str(src),
            '-vf', vf,
            '-t', str(seg.duration_sec),
            '-c:v', 'libx264', '-preset', preset,
            '-pix_fmt', 'yuv420p', '-an', '-r', str(seg.fps),
            str(output),
        ]
        return self._run(cmd, f'video segment {seg.order}')

    def _render_color_segment(
        self, seg: ColorSegmentParams, output: Path, resolution: str, preset: str,
    ) -> bool:
        cmd = [
            self._ffmpeg, '-y',
            '-f', 'lavfi', '-i', f'color=c={seg.color_hex}:s={resolution}:d={seg.duration_sec}',
            '-vf', 'setsar=1',
            '-t', str(seg.duration_sec),
            '-c:v', 'libx264', '-preset', preset,
            '-pix_fmt', 'yuv420p', '-r', str(seg.fps),
            str(output),
        ]
        return self._run(cmd, f'color segment {seg.order}')

    def _render_color_fallback(
        self, output: Path, resolution: str, duration: float, preset: str,
    ) -> bool:
        cmd = [
            self._ffmpeg, '-y',
            '-f', 'lavfi', '-i', f'color=c=#0f172a:s={resolution}:d={duration}',
            '-vf', 'setsar=1', '-t', str(duration),
            '-c:v', 'libx264', '-preset', preset,
            '-pix_fmt', 'yuv420p', '-r', '24',
            str(output),
        ]
        return self._run(cmd, 'color fallback')

    # ── Segment joining ────────────────────────────────────────────────────

    def _join_concat(self, work_dir: Path, seg_paths: list[Path]) -> Path | None:
        if len(seg_paths) == 1:
            return seg_paths[0]
        concat_file = work_dir / 'concat.txt'
        concat_file.write_text(''.join(f"file '{p}'\n" for p in seg_paths))
        output = work_dir / 'concat.mp4'
        cmd = [
            self._ffmpeg, '-y',
            '-f', 'concat', '-safe', '0', '-i', str(concat_file),
            '-c', 'copy',
            str(output),
        ]
        ok = self._run(cmd, 'concat join')
        return output if ok and output.exists() else None

    def _join_xfade(
        self, work_dir: Path, seg_paths: list[Path], seg_durations: list[float],
        effect: str, transition_dur: float, preset: str,
    ) -> Path | None:
        if len(seg_paths) < 2:
            return seg_paths[0] if seg_paths else None

        input_args: list[str] = []
        for p in seg_paths:
            input_args.extend(['-i', str(p)])

        filter_parts: list[str] = []
        cumulative_offset = 0.0

        for i in range(len(seg_paths) - 1):
            src = '[0:v]' if i == 0 else f'[v{i}]'
            cumulative_offset += seg_durations[i] - transition_dur
            offset = max(0, cumulative_offset)
            out_label = '[vout]' if i == len(seg_paths) - 2 else f'[v{i + 1}]'
            filter_parts.append(
                f'{src}[{i + 1}:v]xfade=transition={effect}'
                f':duration={transition_dur}:offset={offset:.3f}{out_label}'
            )

        output = work_dir / 'xfade.mp4'
        cmd = [
            self._ffmpeg, '-y',
            *input_args,
            '-filter_complex', ';'.join(filter_parts),
            '-map', '[vout]',
            '-c:v', 'libx264', '-preset', preset, '-pix_fmt', 'yuv420p',
            str(output),
        ]
        ok = self._run(cmd, 'xfade join')
        return output if ok and output.exists() else None

    # ── Intro / Outro ──────────────────────────────────────────────────────

    def _stitch_intro_outro(
        self, work_dir: Path, main_video: Path,
        intro: IntroClipParams | None, outro: OutroClipParams | None,
    ) -> Path | None:
        parts: list[Path] = []
        if intro and Path(intro.clip_path).exists():
            parts.append(Path(intro.clip_path))
        parts.append(main_video)
        if outro and Path(outro.clip_path).exists():
            parts.append(Path(outro.clip_path))

        if len(parts) == 1:
            return main_video

        concat_file = work_dir / 'stitch.txt'
        concat_file.write_text(''.join(f"file '{p}'\n" for p in parts))
        output = work_dir / 'stitched.mp4'
        cmd = [
            self._ffmpeg, '-y',
            '-f', 'concat', '-safe', '0', '-i', str(concat_file),
            '-c', 'copy',
            str(output),
        ]
        ok = self._run(cmd, 'intro/outro stitch')
        return output if ok and output.exists() else None

    # ── Post-processing ────────────────────────────────────────────────────

    def _apply_text_overlay(
        self, work_dir: Path, input_video: Path, step: TextOverlayParams,
        features: dict[str, bool], total_duration: float, preset: str,
    ) -> Path | None:
        if not features.get('drawtext', False):
            return None

        escaped = step.text.replace("'", "\u2019").replace(":", "\\:")
        font_arg = ''
        if step.font_path and Path(step.font_path).exists():
            font_arg = f":fontfile='{step.font_path}'"

        vf = (
            f"drawtext=text='{escaped}'"
            f":fontsize={step.font_size}:fontcolor={step.font_color}"
            f":borderw={step.border_width}:bordercolor={step.border_color}"
            f":x={step.x}:y={step.y}"
            f"{font_arg}"
            f":enable='between(t,{step.start_sec},{step.start_sec + step.duration_sec})'"
        )

        output = work_dir / f'text_{id(step)}.mp4'
        cmd = [
            self._ffmpeg, '-y',
            '-i', str(input_video),
            '-vf', vf,
            '-c:v', 'libx264', '-preset', preset, '-c:a', 'copy',
            str(output),
        ]
        ok = self._run(cmd, f'text overlay "{step.text[:30]}"')
        return output if ok and output.exists() else None

    def _apply_logo_overlay(
        self, work_dir: Path, input_video: Path, step: LogoOverlayParams,
        video_w: int, video_h: int, preset: str,
    ) -> Path | None:
        logo = Path(step.logo_path)
        if not logo.exists():
            return None

        logo_w = max(int(video_w * step.size_pct), 40)
        pad = step.padding_px

        position_map = {
            'top-right': f'W-w-{pad}:{pad}',
            'top-left': f'{pad}:{pad}',
            'bottom-right': f'W-w-{pad}:H-h-{pad}',
            'bottom-left': f'{pad}:H-h-{pad}',
        }
        overlay_pos = position_map.get(step.position, position_map['top-right'])

        fc = (
            f'[1:v]scale={logo_w}:-1,format=rgba,'
            f'colorchannelmixer=aa={step.opacity}[logo];'
            f'[0:v][logo]overlay={overlay_pos}'
        )
        output = work_dir / 'logo.mp4'
        cmd = [
            self._ffmpeg, '-y',
            '-i', str(input_video), '-i', str(logo),
            '-filter_complex', fc,
            '-c:v', 'libx264', '-preset', preset, '-c:a', 'copy',
            str(output),
        ]
        ok = self._run(cmd, 'logo overlay')
        return output if ok and output.exists() else None

    def _burn_subtitles(
        self, work_dir: Path, input_video: Path, step: SubtitleBurnParams,
        features: dict[str, bool], preset: str,
    ) -> Path | None:
        sub_path = Path(step.subtitle_path)
        if not sub_path.exists():
            return None

        if step.subtitle_format == 'ass' and not features.get('ass', False):
            logger.warning('ASS subtitle support not available in ffmpeg')
            return None

        vf = f"ass='{sub_path}'" if step.subtitle_format == 'ass' else f"subtitles='{sub_path}'"
        output = work_dir / 'subtitled.mp4'
        cmd = [
            self._ffmpeg, '-y',
            '-i', str(input_video),
            '-vf', vf,
            '-c:v', 'libx264', '-preset', preset, '-c:a', 'copy',
            str(output),
        ]
        ok = self._run(cmd, 'subtitle burn')
        return output if ok and output.exists() else None

    def _mux_audio(
        self, work_dir: Path, input_video: Path, step: AudioMuxParams,
    ) -> Path | None:
        audio = Path(step.audio_path)
        if not audio.exists() or audio.stat().st_size < 100:
            return None

        output = work_dir / 'muxed.mp4'
        cmd = [
            self._ffmpeg, '-y',
            '-i', str(input_video), '-i', str(audio),
            '-c:v', 'copy', '-c:a', step.codec, '-shortest',
            str(output),
        ]
        ok = self._run(cmd, 'audio mux')
        return output if ok and output.exists() else None

    def _mix_music(
        self, work_dir: Path, input_video: Path, step: MusicMixParams,
    ) -> Path | None:
        music = Path(step.music_path)
        if not music.exists():
            return None

        loop_filter = 'aloop=loop=-1:size=2e+09,' if step.loop else ''
        fc = f'[1:a]{loop_filter}volume={step.volume}[bg];[0:a][bg]amix=inputs=2:duration=first'

        output = work_dir / 'music.mp4'
        cmd = [
            self._ffmpeg, '-y',
            '-i', str(input_video), '-i', str(music),
            '-filter_complex', fc,
            '-c:v', 'copy', '-c:a', 'aac',
            str(output),
        ]
        ok = self._run(cmd, 'music mix')
        return output if ok and output.exists() else None

    def _extract_thumbnail(
        self, work_dir: Path, input_video: Path, step: ThumbnailParams,
    ) -> Path | None:
        output = work_dir / 'thumb.jpg'
        cmd = [
            self._ffmpeg, '-y',
            '-i', str(input_video),
            '-ss', str(step.time_sec),
            '-frames:v', '1', '-q:v', str(step.quality),
            str(output),
        ]
        ok = self._run(cmd, 'thumbnail')
        return output if ok and output.exists() else None

    # ── Utilities ──────────────────────────────────────────────────────────

    def _detect_features(self) -> dict[str, bool]:
        if self._features is not None:
            return self._features
        features = {'drawtext': False, 'ass': False, 'xfade': False}
        try:
            result = subprocess.run(
                [self._ffmpeg, '-filters'], capture_output=True, check=False,
            )
            stdout = result.stdout
            features['drawtext'] = b'drawtext' in stdout
            features['ass'] = b' ass ' in stdout or b'libass' in stdout
            features['xfade'] = b'xfade' in stdout
        except Exception:
            pass
        self._features = features
        return features

    def _run(self, cmd: list[str], label: str) -> bool:
        """Run an ffmpeg command and return True on success."""
        result = subprocess.run(cmd, check=False, capture_output=True)
        if result.returncode != 0:
            err = result.stderr.decode('utf-8', errors='replace')
            logger.warning('Compiler [%s] failed: %s', label, err[-300:])
            return False
        return True
