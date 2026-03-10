"""Translation pipeline orchestrator — re-dubs an existing video in a new language."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from app.models import GenerationJobRecord, JobStatus, StoryboardSegment, VideoResultRecord
from app.repositories.base import Repository
from app.services.storage import StorageService
from app.services.subtitle_utils import build_srt
from app.services.translation import TranslationService
from app.services.video import VideoService

logger = logging.getLogger(__name__)


def process_translation_job(
    *,
    repo: Repository,
    storage: StorageService,
    translation_service: TranslationService,
    video_service: VideoService,
    job: GenerationJobRecord,
) -> None:
    """Run the translation pipeline for a single job.

    Stages:
        1. LOADING     (5%)  — Load source job's script_lines + storyboard from VideoResultRecord
        2. TRANSLATING (30%) — LLM-translate script lines to target language
        3. NARRATION   (60%) — Synthesize translated script via voice provider
        4. RENDERING   (90%) — Re-render video with new audio + translated SRT
        5. COMPLETED   (100%)
    """
    started = time.perf_counter()
    timings: dict[str, float] = {}

    try:
        # ── LOADING ──────────────────────────────────────────────────
        repo.update_job(job.id, status=JobStatus.LOADING, stage=JobStatus.LOADING, progress_pct=5)
        phase_start = time.perf_counter()

        project = repo.get_project(job.project_id)
        if not project:
            raise ValueError('project_not_found')

        if not job.source_job_id:
            raise ValueError('missing_source_job_id')

        source_result = repo.get_result(job.project_id, job_id=job.source_job_id)
        if not source_result:
            raise ValueError('source_result_not_found')

        if not source_result.script_lines:
            raise ValueError('source_result_missing_script_lines')

        script_lines = source_result.script_lines
        storyboard = source_result.storyboard
        source_language = source_result.language or 'en'

        timings['loading_sec'] = round(time.perf_counter() - phase_start, 3)

        # ── TRANSLATING ─────────────────────────────────────────────
        repo.update_job(job.id, status=JobStatus.TRANSLATING, stage=JobStatus.TRANSLATING, progress_pct=30, timings=timings)
        phase_start = time.perf_counter()

        translated_lines = translation_service.translate_script(
            script_lines=script_lines,
            source_language=source_language,
            target_language=job.language,
            product_context=f'{project.title}: {project.product_description[:500]}',
        )

        # Update storyboard segments with translated script lines
        if len(translated_lines) != len(storyboard):
            logger.warning('Translation returned %d lines but storyboard has %d segments', len(translated_lines), len(storyboard))

        translated_storyboard = []
        for i, segment in enumerate(storyboard):
            translated_segment = StoryboardSegment(
                order=segment.order,
                script_line=translated_lines[i] if i < len(translated_lines) else segment.script_line,
                image_asset_id=segment.image_asset_id,
                start_sec=segment.start_sec,
                duration_sec=segment.duration_sec,
                media_type=segment.media_type,
                video_path=segment.video_path,
            )
            translated_storyboard.append(translated_segment)

        timings['translating_sec'] = round(time.perf_counter() - phase_start, 3)

        # ── NARRATION ────────────────────────────────────────────────
        repo.update_job(job.id, status=JobStatus.NARRATION, stage=JobStatus.NARRATION, progress_pct=60, timings=timings)
        phase_start = time.perf_counter()

        transcript = '\n'.join(translated_lines)
        transcript_key = f'projects/{project.id}/outputs/{job.id}.txt'
        audio_key = f'projects/{project.id}/outputs/{job.id}.mp3'

        storage.store_text(transcript_key, transcript)

        from app.config import get_settings
        from app.services.voice.factory import build_voice_provider

        settings = get_settings()
        if settings.use_mock_ai:
            from app.services.voice.base import MOCK_SILENT_MP3
            audio_payload = MOCK_SILENT_MP3
        else:
            provider = build_voice_provider(job.voice_provider, settings)
            audio_payload = provider.synthesize(
                transcript[:3000],
                voice_gender=job.voice_gender,
                language=job.language,
            )

        storage.store_bytes(audio_key, audio_payload, content_type='audio/mpeg')
        timings['narration_sec'] = round(time.perf_counter() - phase_start, 3)

        transcript_url = storage.get_public_url(transcript_key)

        # ── RENDERING ────────────────────────────────────────────────
        repo.update_job(job.id, status=JobStatus.RENDERING, stage=JobStatus.RENDERING, progress_pct=90, timings=timings)
        phase_start = time.perf_counter()

        from app.services.music import select_music_path
        music_path = select_music_path(job.background_music, job.voice_style)

        # Build effects config for transitions and overlays
        from app.services.effects import VideoEffectsConfig
        job._project_title = project.title
        effects_config = VideoEffectsConfig.from_job(job)

        # Generate captions if needed
        ass_subtitle_file = None
        caption_style = job.caption_style or 'none'
        if caption_style != 'none':
            from app.services.transcription import build_transcription_backend, generate_ass_subtitles

            settings = get_settings()
            audio_path = (settings.local_data_dir / settings.local_storage_dir
                          / 'projects' / project.id / 'outputs' / f'{job.id}.mp3')
            ass_resolution, _ = video_service._resolution_for(job.aspect_ratio)
            backend = build_transcription_backend(
                settings.transcription_backend, settings, script_lines=translated_lines,
            )
            word_timings = backend.transcribe(audio_path, language=job.language)
            if word_timings:
                ass_content = generate_ass_subtitles(
                    word_timings, caption_style=caption_style, resolution=ass_resolution,
                )
                ass_key = f'projects/{project.id}/outputs/{job.id}.ass'
                storage.store_text(ass_key, ass_content)

                import tempfile
                ass_subtitle_file = Path(tempfile.mktemp(suffix='.ass', prefix='novareel-'))
                ass_subtitle_file.write_text(ass_content)

        video_key, duration_sec, resolution, thumbnail_key = video_service.render_video(
            project=project,
            job_id=job.id,
            aspect_ratio=job.aspect_ratio,
            storyboard=translated_storyboard,
            storage=storage,
            music_path=music_path,
            effects_config=effects_config,
            ass_subtitle_path=ass_subtitle_file,
        )

        # Cleanup temp ASS file
        if ass_subtitle_file and ass_subtitle_file.exists():
            ass_subtitle_file.unlink(missing_ok=True)

        subtitle_key = f'projects/{project.id}/outputs/{job.id}.srt'
        storage.store_text(subtitle_key, build_srt(translated_storyboard))

        timings['rendering_sec'] = round(time.perf_counter() - phase_start, 3)

        result = VideoResultRecord(
            project_id=project.id,
            job_id=job.id,
            video_s3_key=video_key,
            video_url=storage.get_public_url(video_key),
            duration_sec=duration_sec,
            resolution=resolution,
            thumbnail_key=thumbnail_key,
            transcript_key=transcript_key,
            transcript_url=transcript_url,
            subtitle_key=subtitle_key,
            subtitle_url=storage.get_public_url(subtitle_key),
            storyboard=translated_storyboard,
            script_lines=translated_lines,
            language=job.language,
            completed_at=datetime.now(UTC),
        )

        repo.set_result(project.id, job.id, result)
        month = datetime.now(UTC).strftime('%Y-%m')
        repo.increment_usage(project.owner_id, month)
        repo.record_analytics_event(
            owner_id=project.owner_id,
            event_name='translation_completed',
            project_id=project.id,
            job_id=job.id,
            properties={
                'source_job_id': job.source_job_id,
                'target_language': job.language,
                'duration_sec': duration_sec,
            },
        )

        timings['total_sec'] = round(time.perf_counter() - started, 3)
        repo.update_job(
            job.id,
            status=JobStatus.COMPLETED,
            stage=JobStatus.COMPLETED,
            progress_pct=100,
            timings=timings,
            error_code=None,
        )

    except Exception as exc:
        logger.exception('Translation job %s failed', job.id)
        project = repo.get_project(job.project_id)
        if project:
            repo.record_analytics_event(
                owner_id=project.owner_id,
                event_name='translation_failed',
                project_id=project.id,
                job_id=job.id,
                properties={
                    'error_code': str(exc)[:160],
                    'source_job_id': job.source_job_id,
                },
            )
        repo.update_job(
            job.id,
            status=JobStatus.FAILED,
            stage=JobStatus.FAILED,
            progress_pct=100,
            error_code=str(exc)[:160],
            timings={'total_sec': round(time.perf_counter() - started, 3)},
        )
