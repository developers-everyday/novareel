'use client';

import { useAuth } from '@clerk/nextjs';
import Image from 'next/image';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  createProject,
  generateProject,
  getJob,
  getProjectResult,
  getUploadUrl,
  getUsage,
  listProjectJobs,
  listProjects,
  trackAnalyticsEvent,
  uploadAsset
} from '@/lib/api';
import type { GenerationJob, Project, UsageSummary, VideoResult } from '@/lib/contracts';
import { JobStatusCard } from '@/components/job-status-card';

const pollableStatuses = new Set<GenerationJob['status']>(['queued', 'scripting', 'matching', 'narration', 'rendering']);

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

export function ProjectStudio() {
  const { getToken } = useAuth();

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [voiceStyle, setVoiceStyle] = useState('energetic');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [brandColors, setBrandColors] = useState('#f97316,#0f172a');
  const [files, setFiles] = useState<File[]>([]);

  const [projectId, setProjectId] = useState<string | null>(null);
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [projectJobs, setProjectJobs] = useState<GenerationJob[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [result, setResult] = useState<VideoResult | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);

  const [csatRating, setCsatRating] = useState('5');
  const [csatComment, setCsatComment] = useState('');
  const [csatSent, setCsatSent] = useState(false);
  const [previewTracked, setPreviewTracked] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const filePreviews = useMemo(
    () => files.map((file) => ({ name: file.name, url: URL.createObjectURL(file) })),
    [files]
  );

  useEffect(() => {
    return () => {
      filePreviews.forEach((preview) => URL.revokeObjectURL(preview.url));
    };
  }, [filePreviews]);

  async function refreshSideData(targetProjectId?: string) {
    const token = await getToken();
    const [usageSummary, projectItems] = await Promise.all([getUsage(token), listProjects(token)]);

    setUsage(usageSummary);
    setProjects(projectItems);

    const nextProjectId = targetProjectId ?? projectId;
    if (nextProjectId) {
      const jobs = await listProjectJobs(nextProjectId, token);
      setProjectJobs(jobs);
    }
  }

  useEffect(() => {
    refreshSideData().catch(() => undefined);
  }, []);

  useEffect(() => {
    let interval: NodeJS.Timeout | undefined;

    async function pollJob() {
      if (!job || !pollableStatuses.has(job.status)) {
        return;
      }

      const token = await getToken();
      const nextJob = await getJob(job.id, token);
      setJob(nextJob);

      if ((nextJob.status === 'completed' || nextJob.status === 'failed') && projectId) {
        const jobs = await listProjectJobs(projectId, token);
        setProjectJobs(jobs);
      }

      if (nextJob.status === 'completed' && projectId) {
        const nextResult = await getProjectResult(projectId, token);
        setResult(nextResult);
        const summary = await getUsage(token);
        setUsage(summary);
      }
    }

    if (job && pollableStatuses.has(job.status)) {
      interval = setInterval(() => {
        pollJob().catch((err) => setError(err instanceof Error ? err.message : 'Failed to refresh job status'));
      }, 3000);
    }

    return () => {
      if (interval) {
        clearInterval(interval);
      }
    };
  }, [job, projectId, getToken]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    setCsatSent(false);
    setPreviewTracked(false);

    try {
      if (!title.trim() || !description.trim()) {
        throw new Error('Title and product description are required.');
      }

      if (files.length === 0) {
        throw new Error('Add at least one product image.');
      }

      const token = await getToken();

      const project = await createProject(
        {
          title,
          product_description: description,
          brand_prefs: {
            colors: brandColors
              .split(',')
              .map((value) => value.trim())
              .filter(Boolean)
          }
        },
        token
      );

      setProjectId(project.id);
      setResult(null);

      for (const file of files) {
        const upload = await getUploadUrl(
          project.id,
          {
            filename: file.name,
            content_type: file.type || 'image/jpeg',
            file_size: file.size
          },
          token
        );

        await uploadAsset(upload.upload_url, file, upload.headers, token);
      }

      const idempotencyKey =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `${project.id}-${Date.now()}`;

      const queuedJob = await generateProject(
        project.id,
        {
          aspect_ratio: aspectRatio,
          voice_style: voiceStyle,
          idempotency_key: idempotencyKey
        },
        token
      );

      setJob(queuedJob);
      const jobs = await listProjectJobs(project.id, token);
      setProjectJobs(jobs);
      await refreshSideData(project.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Video generation failed');
    } finally {
      setBusy(false);
    }
  }

  async function onVideoPreview() {
    if (previewTracked || !projectId || !result) {
      return;
    }

    try {
      const token = await getToken();
      await trackAnalyticsEvent(
        {
          event_name: 'video_preview_played',
          project_id: projectId,
          job_id: job?.id,
          properties: { resolution: result.resolution }
        },
        token
      );
      setPreviewTracked(true);
    } catch {
      // Avoid blocking playback if analytics is unavailable.
    }
  }

  async function onDownloadClicked(kind: 'video' | 'transcript' | 'subtitle') {
    if (!projectId) {
      return;
    }

    try {
      const token = await getToken();
      await trackAnalyticsEvent(
        {
          event_name: 'video_download_clicked',
          project_id: projectId,
          job_id: job?.id,
          properties: { asset_type: kind }
        },
        token
      );
    } catch {
      // Ignore analytics failure in UI flow.
    }
  }

  async function submitCsat() {
    if (!projectId || csatSent) {
      return;
    }

    try {
      const token = await getToken();
      await trackAnalyticsEvent(
        {
          event_name: 'csat_submitted',
          project_id: projectId,
          job_id: job?.id,
          properties: { rating: Number(csatRating), comment: csatComment.trim() }
        },
        token
      );
      setCsatSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit CSAT');
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
      <form className="surface space-y-5 p-6" onSubmit={onSubmit}>
        <div>
          <h2 className="text-2xl font-semibold text-ink">Build your product video</h2>
          <p className="mt-1 text-sm text-slate-600">Upload product photos and NovaReel will generate a 30-60 sec highlight video.</p>
        </div>

        <label className="block text-sm font-medium text-slate-700">
          Product title
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Wireless Charging Dock"
            maxLength={200}
            required
          />
        </label>

        <label className="block text-sm font-medium text-slate-700">
          Product description
          <textarea
            className="mt-1 min-h-28 w-full rounded-lg border border-slate-300 px-3 py-2"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Describe key product benefits, target buyer, and tone."
            required
          />
        </label>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Aspect ratio
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={aspectRatio}
              onChange={(event) => setAspectRatio(event.target.value)}
            >
              <option value="16:9">16:9 (landscape)</option>
              <option value="1:1">1:1 (square)</option>
              <option value="9:16">9:16 (vertical)</option>
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Voice style
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={voiceStyle}
              onChange={(event) => setVoiceStyle(event.target.value)}
            >
              <option value="energetic">Energetic</option>
              <option value="professional">Professional</option>
              <option value="friendly">Friendly</option>
            </select>
          </label>
        </div>

        <label className="block text-sm font-medium text-slate-700">
          Brand colors (comma-separated)
          <input
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
            value={brandColors}
            onChange={(event) => setBrandColors(event.target.value)}
            placeholder="#f97316,#0f172a"
          />
        </label>

        <label className="block text-sm font-medium text-slate-700">
          Product images
          <input
            className="mt-2 block w-full text-sm"
            type="file"
            accept="image/*"
            multiple
            onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
          />
        </label>

        {filePreviews.length > 0 ? (
          <div className="grid grid-cols-3 gap-3">
            {filePreviews.slice(0, 6).map((preview) => (
              <div key={preview.url} className="relative h-24 overflow-hidden rounded-lg border border-slate-200">
                <Image src={preview.url} alt={preview.name} fill className="object-cover" unoptimized />
              </div>
            ))}
          </div>
        ) : null}

        {error ? <p className="rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p> : null}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-ink px-4 py-3 font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? 'Preparing your generation job...' : 'Generate video'}
        </button>
      </form>

      <div className="space-y-6">
        <section className="surface p-5">
          <h3 className="text-lg font-semibold text-ink">Usage this month</h3>
          {usage ? (
            <div className="mt-3 space-y-1 text-sm text-slate-700">
              <p>Generated videos: {usage.videos_generated}</p>
              <p>Quota limit: {usage.quota_limit}</p>
              <p>Remaining: {usage.remaining}</p>
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-600">Loading usage...</p>
          )}
        </section>

        {job ? <JobStatusCard job={job} /> : null}

        {result ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Latest render</h3>
            <video className="mt-3 w-full rounded-lg" controls src={result.video_url} onPlay={onVideoPreview} />
            <p className="mt-2 text-sm text-slate-600">
              {result.resolution} · {Math.round(result.duration_sec)} sec
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <a
                href={result.video_url}
                download
                target="_blank"
                rel="noreferrer"
                onClick={() => onDownloadClicked('video').catch(() => undefined)}
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Download MP4
              </a>
              {result.transcript_url ? (
                <a
                  href={result.transcript_url}
                  download
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => onDownloadClicked('transcript').catch(() => undefined)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Download Transcript
                </a>
              ) : null}
              {result.subtitle_url ? (
                <a
                  href={result.subtitle_url}
                  download
                  target="_blank"
                  rel="noreferrer"
                  onClick={() => onDownloadClicked('subtitle').catch(() => undefined)}
                  className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                >
                  Download Subtitles
                </a>
              ) : null}
            </div>
            {projectId ? <p className="mt-2 text-xs text-slate-500">Project ID: {projectId}</p> : null}
          </section>
        ) : null}

        {result && !csatSent ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Rate your first output</h3>
            <p className="mt-1 text-sm text-slate-600">This helps us prioritize improvements for the private beta.</p>
            <div className="mt-3 grid gap-3">
              <label className="text-sm font-medium text-slate-700">
                CSAT score (1-5)
                <select
                  value={csatRating}
                  onChange={(event) => setCsatRating(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                >
                  <option value="5">5 - Excellent</option>
                  <option value="4">4 - Good</option>
                  <option value="3">3 - Neutral</option>
                  <option value="2">2 - Poor</option>
                  <option value="1">1 - Very poor</option>
                </select>
              </label>
              <label className="text-sm font-medium text-slate-700">
                Optional comment
                <textarea
                  value={csatComment}
                  onChange={(event) => setCsatComment(event.target.value)}
                  className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2"
                  placeholder="What should NovaReel improve next?"
                />
              </label>
              <button
                type="button"
                onClick={() => submitCsat().catch(() => undefined)}
                className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
              >
                Submit feedback
              </button>
            </div>
          </section>
        ) : null}

        {projectJobs.length > 0 ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Current project jobs</h3>
            <ul className="mt-3 space-y-2 text-sm">
              {projectJobs.slice(0, 6).map((item) => (
                <li key={item.id} className="rounded-lg border border-slate-100 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-mono text-xs text-slate-700">{item.id.slice(0, 8)}</p>
                    <p className="text-xs capitalize text-slate-600">{item.status}</p>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">{item.progress_pct}% · updated {formatDate(item.updated_at)}</p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {projects.length > 0 ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Recent projects</h3>
            <ul className="mt-3 space-y-2 text-sm">
              {projects.slice(0, 5).map((project) => (
                <li key={project.id} className="rounded-lg border border-slate-100 p-3">
                  <p className="font-medium text-ink">{project.title}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    created {formatDate(project.created_at)} · assets {project.asset_ids.length}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </div>
  );
}
