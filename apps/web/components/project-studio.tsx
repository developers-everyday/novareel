'use client';

import { useAuth } from '@clerk/nextjs';
import Image from 'next/image';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import {
  createProject,
  generateProject,
  generateVariants,
  getJob,
  getProjectResult,
  getStoryboard,
  getUploadUrl,
  getUsage,
  approveStoryboard,
  updateStoryboard,
  generateMetadata,
  publishToYouTube,
  listProjectJobs,
  listProjects,
  listSocialConnections,
  trackAnalyticsEvent,
  translateProject,
  uploadAsset
} from '@/lib/api';
import type { GenerationJob, Project, UsageSummary, VideoResult, StoryboardScene, SocialConnection, MetadataResponse } from '@/lib/contracts';
import { JobStatusCard } from '@/components/job-status-card';

const pollableStatuses = new Set<GenerationJob['status']>(['queued', 'analyzing', 'scripting', 'matching', 'narration', 'rendering', 'loading', 'translating', 'awaiting_approval']);

const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Spanish (Español)' },
  { code: 'fr', label: 'French (Français)' },
  { code: 'de', label: 'German (Deutsch)' },
  { code: 'ar', label: 'Arabic (العربية)' },
  { code: 'hi', label: 'Hindi (हिन्दी)' },
  { code: 'ja', label: 'Japanese (日本語)' },
  { code: 'zh', label: 'Chinese (中文)' },
  { code: 'ko', label: 'Korean (한국어)' },
  { code: 'pt', label: 'Portuguese (Português)' },
  { code: 'it', label: 'Italian (Italiano)' },
  { code: 'ru', label: 'Russian (Русский)' },
  { code: 'tr', label: 'Turkish (Türkçe)' },
  { code: 'nl', label: 'Dutch (Nederlands)' },
  { code: 'pl', label: 'Polish (Polski)' },
  { code: 'sv', label: 'Swedish (Svenska)' },
  { code: 'th', label: 'Thai (ไทย)' },
  { code: 'vi', label: 'Vietnamese (Tiếng Việt)' },
  { code: 'id', label: 'Indonesian (Bahasa)' },
  { code: 'ms', label: 'Malay (Melayu)' },
] as const;

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

export function ProjectStudio() {
  const { getToken } = useAuth();

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [voiceStyle, setVoiceStyle] = useState('energetic');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [voiceProvider, setVoiceProvider] = useState('polly');
  const [voiceGender, setVoiceGender] = useState('female');
  const [language, setLanguage] = useState('en');
  const [backgroundMusic, setBackgroundMusic] = useState('auto');
  const [scriptTemplate, setScriptTemplate] = useState('product_showcase');
  const [videoStyle, setVideoStyle] = useState('product_only');
  const [captionStyle, setCaptionStyle] = useState('none');
  const [transitionStyle, setTransitionStyle] = useState('none');
  const [showTitleCard, setShowTitleCard] = useState(false);
  const [ctaText, setCtaText] = useState('');
  const [brandColors, setBrandColors] = useState('#f97316,#0f172a');
  const [files, setFiles] = useState<File[]>([]);

  // Translation modal state
  const [showTranslateModal, setShowTranslateModal] = useState(false);
  const [translateLanguages, setTranslateLanguages] = useState<string[]>([]);
  const [translateVoiceProvider, setTranslateVoiceProvider] = useState('edge_tts');
  const [translateVoiceGender, setTranslateVoiceGender] = useState('female');
  const [translating, setTranslating] = useState(false);

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

  // Phase 3 state
  const [autoApprove, setAutoApprove] = useState(true);
  const [storyboardScenes, setStoryboardScenes] = useState<StoryboardScene[]>([]);
  const [showStoryboardEditor, setShowStoryboardEditor] = useState(false);
  const [showPublishModal, setShowPublishModal] = useState(false);
  const [publishTitle, setPublishTitle] = useState('');
  const [publishDescription, setPublishDescription] = useState('');
  const [publishTags, setPublishTags] = useState('');
  const [publishPrivacy, setPublishPrivacy] = useState<'public' | 'unlisted' | 'private'>('private');
  const [publishing, setPublishing] = useState(false);
  const [generatingMetadata, setGeneratingMetadata] = useState(false);
  const [showVariantsModal, setShowVariantsModal] = useState(false);
  const [variantCount, setVariantCount] = useState(3);
  const [generatingVariants, setGeneratingVariants] = useState(false);

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
        const nextResult = await getProjectResult(projectId, undefined, token);
        setResult(nextResult);
        const summary = await getUsage(token);
        setUsage(summary);
      }

      // Phase 3: Load storyboard when awaiting approval
      if (nextJob.status === 'awaiting_approval' && projectId) {
        try {
          const sb = await getStoryboard(projectId, nextJob.id, token);
          setStoryboardScenes(sb.scenes || []);
          setShowStoryboardEditor(true);
        } catch {
          // Storyboard may not be ready yet
        }
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
          voice_provider: voiceProvider,
          voice_gender: voiceGender,
          language: language,
          background_music: backgroundMusic,
          idempotency_key: idempotencyKey,
          script_template: scriptTemplate,
          video_style: videoStyle,
          caption_style: captionStyle,
          transition_style: transitionStyle,
          show_title_card: showTitleCard,
          cta_text: ctaText || undefined,
          auto_approve: autoApprove,
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

  function toggleTranslateLanguage(lang: string) {
    setTranslateLanguages((prev) =>
      prev.includes(lang) ? prev.filter((l) => l !== lang) : [...prev, lang]
    );
  }

  // Phase 3: Storyboard scene edit handler
  function onSceneScriptChange(order: number, newLine: string) {
    setStoryboardScenes((prev) =>
      prev.map((s) => (s.order === order ? { ...s, script_line: newLine } : s))
    );
  }

  async function onStoryboardApprove() {
    if (!projectId || !job) return;
    setBusy(true);
    setError(null);
    try {
      const token = await getToken();
      // Save edits first
      await updateStoryboard(projectId, job.id, storyboardScenes, token);
      // Approve → resume pipeline
      const resumed = await approveStoryboard(projectId, job.id, token);
      setJob(resumed);
      setShowStoryboardEditor(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Storyboard approval failed');
    } finally {
      setBusy(false);
    }
  }

  async function onGenerateMetadata() {
    if (!projectId || !job) return;
    setGeneratingMetadata(true);
    setError(null);
    try {
      const token = await getToken();
      const meta = await generateMetadata(projectId, job.id, { platforms: ['youtube'] }, token);
      if (meta.youtube) {
        const yt = meta.youtube as Record<string, string>;
        setPublishTitle(yt.title || '');
        setPublishDescription(yt.description || '');
        setPublishTags((yt.tags as unknown as string[] || []).join(', '));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Metadata generation failed');
    } finally {
      setGeneratingMetadata(false);
    }
  }

  async function onPublishYouTube() {
    if (!projectId || !job) return;
    setPublishing(true);
    setError(null);
    try {
      const token = await getToken();
      const record = await publishToYouTube(projectId, job.id, {
        title: publishTitle,
        description: publishDescription,
        tags: publishTags.split(',').map((t) => t.trim()).filter(Boolean),
        privacy: publishPrivacy,
      }, token);
      setShowPublishModal(false);
      alert(`Published! YouTube URL: ${record.platform_url}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Publishing failed');
    } finally {
      setPublishing(false);
    }
  }

  async function onGenerateVariants() {
    if (!projectId) return;
    setGeneratingVariants(true);
    setError(null);
    try {
      const token = await getToken();
      const variantJobs = await generateVariants(projectId, { variant_count: variantCount }, token);
      setShowVariantsModal(false);
      if (variantJobs.length > 0) {
        setJob(variantJobs[0]);
      }
      await refreshSideData(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Variant generation failed');
    } finally {
      setGeneratingVariants(false);
    }
  }

  async function onTranslateSubmit() {
    if (!projectId || !job || translateLanguages.length === 0) {
      return;
    }
    setTranslating(true);
    setError(null);
    try {
      const token = await getToken();
      const newJobs = await translateProject(projectId, job.id, {
        target_languages: translateLanguages,
        voice_provider: translateVoiceProvider,
        voice_gender: translateVoiceGender,
      }, token);
      setShowTranslateModal(false);
      setTranslateLanguages([]);
      // Poll the first translation job
      if (newJobs.length > 0) {
        setJob(newJobs[0]);
      }
      await refreshSideData(projectId);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Translation request failed');
    } finally {
      setTranslating(false);
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

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Voice engine
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={voiceProvider}
              onChange={(event) => setVoiceProvider(event.target.value)}
            >
              <option value="polly">Amazon Polly (Default)</option>
              <option value="edge_tts">Edge TTS (Free · 50+ languages)</option>
              <option value="elevenlabs">ElevenLabs (Premium)</option>
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Voice gender
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={voiceGender}
              onChange={(event) => setVoiceGender(event.target.value)}
            >
              <option value="female">Female</option>
              <option value="male">Male</option>
            </select>
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Language
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
            >
              {SUPPORTED_LANGUAGES.map((lang) => (
                <option key={lang.code} value={lang.code}>{lang.label}</option>
              ))}
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Background music
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={backgroundMusic}
              onChange={(event) => setBackgroundMusic(event.target.value)}
            >
              <option value="auto">Auto (match voice style)</option>
              <option value="upbeat">Upbeat</option>
              <option value="calm">Calm</option>
              <option value="corporate">Corporate</option>
              <option value="luxury">Luxury</option>
              <option value="none">No music</option>
            </select>
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Script style
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={scriptTemplate}
              onChange={(event) => setScriptTemplate(event.target.value)}
            >
              <option value="product_showcase">Product Showcase (Default)</option>
              <option value="problem_solution">Problem / Solution</option>
              <option value="comparison">Product Comparison</option>
              <option value="unboxing">Unboxing Experience</option>
              <option value="testimonial">Customer Testimonial</option>
              <option value="how_to">How-To / Tutorial</option>
              <option value="seasonal">Seasonal Promotion</option>
              <option value="luxury">Luxury / Premium</option>
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Video style
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={videoStyle}
              onChange={(event) => setVideoStyle(event.target.value)}
            >
              <option value="product_only">Product Images Only (Default)</option>
              <option value="product_lifestyle">Product + Lifestyle B-Roll</option>
              <option value="lifestyle_focus">Lifestyle-Focused</option>
            </select>
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">
            Caption style
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={captionStyle}
              onChange={(event) => setCaptionStyle(event.target.value)}
            >
              <option value="none">No captions</option>
              <option value="simple">Simple subtitles</option>
              <option value="word_highlight">Word highlight</option>
              <option value="karaoke">Karaoke</option>
            </select>
          </label>

          <label className="block text-sm font-medium text-slate-700">
            Transition effect
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={transitionStyle}
              onChange={(event) => setTransitionStyle(event.target.value)}
            >
              <option value="none">None (cut)</option>
              <option value="crossfade">Crossfade</option>
              <option value="slide_left">Slide left</option>
              <option value="slide_right">Slide right</option>
              <option value="slide_up">Slide up</option>
              <option value="slide_down">Slide down</option>
              <option value="wipe_left">Wipe left</option>
              <option value="wipe_right">Wipe right</option>
              <option value="fade_black">Fade to black</option>
              <option value="fade_white">Fade to white</option>
              <option value="circle_open">Circle open</option>
              <option value="circle_close">Circle close</option>
              <option value="dissolve">Dissolve</option>
            </select>
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="flex items-center gap-2 text-sm font-medium text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              className="rounded border-slate-300"
              checked={showTitleCard}
              onChange={(event) => setShowTitleCard(event.target.checked)}
            />
            Show title card
          </label>

          <label className="block text-sm font-medium text-slate-700">
            CTA text (optional)
            <input
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
              value={ctaText}
              onChange={(event) => setCtaText(event.target.value)}
              placeholder="Shop now at example.com"
              maxLength={100}
            />
          </label>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="flex items-center gap-2 text-sm font-medium text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              className="rounded border-slate-300"
              checked={!autoApprove}
              onChange={(event) => setAutoApprove(!event.target.checked)}
            />
            Review storyboard before rendering
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

        {showStoryboardEditor && job?.status === 'awaiting_approval' && storyboardScenes.length > 0 ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Edit Storyboard</h3>
            <p className="mt-1 text-sm text-slate-600">Review and edit your script lines before rendering. Reorder or tweak narration text.</p>
            <div className="mt-4 space-y-3">
              {storyboardScenes.map((scene) => (
                <div key={scene.order} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-600">
                      {scene.order}
                    </span>
                    <span className="text-xs text-slate-500">
                      {scene.start_sec.toFixed(1)}s &ndash; {(scene.start_sec + scene.duration_sec).toFixed(1)}s
                      {scene.media_type === 'video' ? ' (B-roll)' : ''}
                    </span>
                  </div>
                  <textarea
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    rows={2}
                    value={scene.script_line}
                    onChange={(e) => onSceneScriptChange(scene.order, e.target.value)}
                  />
                </div>
              ))}
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => onStoryboardApprove().catch(() => undefined)}
                className="rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-60"
              >
                {busy ? 'Approving...' : 'Approve & Render'}
              </button>
            </div>
          </section>
        ) : null}

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
              {job && job.status === 'completed' && job.job_type !== 'translation' ? (
                <>
                  <button
                    type="button"
                    onClick={() => setShowTranslateModal(true)}
                    className="rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    Translate
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowPublishModal(true); onGenerateMetadata().catch(() => undefined); }}
                    className="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700"
                  >
                    Publish
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowVariantsModal(true)}
                    className="rounded-lg bg-purple-600 px-3 py-2 text-sm font-medium text-white hover:bg-purple-700"
                  >
                    A/B Variants
                  </button>
                </>
              ) : null}
            </div>
            {result.language && result.language !== 'en' ? (
              <p className="mt-2 text-xs text-blue-600 font-medium">Language: {result.language.toUpperCase()}</p>
            ) : null}
            {projectId ? <p className="mt-2 text-xs text-slate-500">Project ID: {projectId}</p> : null}
          </section>
        ) : null}

        {showTranslateModal ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Translate video</h3>
            <p className="mt-1 text-sm text-slate-600">Select target languages and voice settings for dubbed versions.</p>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {SUPPORTED_LANGUAGES.filter((lang) => lang.code !== 'en').map((lang) => (
                <label key={lang.code} className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={translateLanguages.includes(lang.code)}
                    onChange={() => toggleTranslateLanguage(lang.code)}
                    className="rounded border-slate-300"
                  />
                  {lang.label}
                </label>
              ))}
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className="block text-sm font-medium text-slate-700">
                Voice engine
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={translateVoiceProvider}
                  onChange={(e) => setTranslateVoiceProvider(e.target.value)}
                >
                  <option value="edge_tts">Edge TTS (Free · 50+ languages)</option>
                  <option value="polly">Amazon Polly</option>
                  <option value="elevenlabs">ElevenLabs (Premium)</option>
                </select>
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Voice gender
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={translateVoiceGender}
                  onChange={(e) => setTranslateVoiceGender(e.target.value)}
                >
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                </select>
              </label>
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                disabled={translating || translateLanguages.length === 0}
                onClick={() => onTranslateSubmit().catch(() => undefined)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {translating ? 'Submitting...' : `Translate to ${translateLanguages.length} language${translateLanguages.length !== 1 ? 's' : ''}`}
              </button>
              <button
                type="button"
                onClick={() => setShowTranslateModal(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </section>
        ) : null}

        {showPublishModal ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Publish to YouTube</h3>
            <p className="mt-1 text-sm text-slate-600">
              {generatingMetadata ? 'Generating metadata with AI...' : 'Edit metadata and publish your video.'}
            </p>
            <div className="mt-3 grid gap-3">
              <label className="block text-sm font-medium text-slate-700">
                Title
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={publishTitle}
                  onChange={(e) => setPublishTitle(e.target.value)}
                  placeholder="Video title"
                  maxLength={100}
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Description
                <textarea
                  className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                  value={publishDescription}
                  onChange={(e) => setPublishDescription(e.target.value)}
                  placeholder="Video description"
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Tags (comma-separated)
                <input
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={publishTags}
                  onChange={(e) => setPublishTags(e.target.value)}
                  placeholder="product, marketing, demo"
                />
              </label>
              <label className="block text-sm font-medium text-slate-700">
                Privacy
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={publishPrivacy}
                  onChange={(e) => setPublishPrivacy(e.target.value as 'public' | 'unlisted' | 'private')}
                >
                  <option value="private">Private</option>
                  <option value="unlisted">Unlisted</option>
                  <option value="public">Public</option>
                </select>
              </label>
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                disabled={publishing || !publishTitle.trim()}
                onClick={() => onPublishYouTube().catch(() => undefined)}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                {publishing ? 'Publishing...' : 'Publish to YouTube'}
              </button>
              <button
                type="button"
                onClick={() => setShowPublishModal(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </section>
        ) : null}

        {showVariantsModal ? (
          <section className="surface p-5">
            <h3 className="text-lg font-semibold text-ink">Generate A/B Variants</h3>
            <p className="mt-1 text-sm text-slate-600">Create multiple video variants with different styles for A/B testing.</p>
            <div className="mt-3">
              <label className="block text-sm font-medium text-slate-700">
                Number of variants
                <select
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"
                  value={variantCount}
                  onChange={(e) => setVariantCount(Number(e.target.value))}
                >
                  <option value={2}>2 variants</option>
                  <option value={3}>3 variants</option>
                  <option value={4}>4 variants</option>
                  <option value={5}>5 variants</option>
                </select>
              </label>
            </div>
            <div className="mt-4 flex gap-2">
              <button
                type="button"
                disabled={generatingVariants}
                onClick={() => onGenerateVariants().catch(() => undefined)}
                className="rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-60"
              >
                {generatingVariants ? 'Generating...' : `Generate ${variantCount} variants`}
              </button>
              <button
                type="button"
                onClick={() => setShowVariantsModal(false)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
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
