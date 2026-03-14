import type {
  AdminOverview, AnalyticsEventRecord, GenerationJob, Project, UsageSummary, VideoResult,
  BrandKit, BrandKitInput, LibraryAsset, LibraryAssetUploadInput, LibraryAssetUploadResponse,
  MetadataRequest, MetadataResponse, SocialConnection, PublishRequest, PublishRecord,
  Storyboard, StoryboardScene, GenerateVariantsInput,
} from '@/lib/contracts';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? (process.env.NODE_ENV === 'production' ? '' : 'http://localhost:8000');

type JsonObject = Record<string, unknown>;

function isApiAssetUploadUrl(uploadUrl: string): boolean {
  try {
    const base = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
    const { pathname } = new URL(uploadUrl, base);
    return /^\/v1\/projects\/[^/]+\/assets\/[^/]+:upload$/.test(pathname);
  } catch {
    return false;
  }
}

async function apiRequest<T>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const headers = new Headers(options.headers);

  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    cache: 'no-store'
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => ({}))) as JsonObject;
    const detail = typeof payload.detail === 'string' ? payload.detail : response.statusText;
    throw new Error(`API ${response.status}: ${detail}`);
  }

  return (await response.json()) as T;
}

export interface CreateProjectInput {
  title: string;
  product_description: string;
  brand_prefs: Record<string, unknown>;
}

export interface UploadUrlResponse {
  asset_id: string;
  object_key: string;
  upload_url: string;
  method: 'PUT';
  headers: Record<string, string>;
}

export async function createProject(input: CreateProjectInput, token?: string | null): Promise<Project> {
  return apiRequest<Project>('/v1/projects', {
    method: 'POST',
    body: JSON.stringify(input)
  }, token);
}

export async function getUploadUrl(
  projectId: string,
  input: { filename: string; content_type: string; file_size: number },
  token?: string | null
): Promise<UploadUrlResponse> {
  return apiRequest<UploadUrlResponse>(`/v1/projects/${projectId}/assets:upload-url`, {
    method: 'POST',
    body: JSON.stringify(input)
  }, token);
}

export async function uploadAsset(uploadUrl: string, file: File, headers: Record<string, string>, token?: string | null): Promise<void> {
  const mergedHeaders: Record<string, string> = { ...headers };

  // Local/dev uploads go back through the API and require auth, but presigned S3 PUTs must not
  // include the Clerk bearer token or the signature validation will fail.
  if (token && isApiAssetUploadUrl(uploadUrl)) {
    mergedHeaders['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: mergedHeaders,
    body: file
  });

  if (!response.ok) {
    const contentType = response.headers.get('content-type') ?? '';
    let detail = '';

    if (contentType.includes('application/json')) {
      const payload = (await response.json().catch(() => ({}))) as JsonObject;
      detail = typeof payload.detail === 'string' ? payload.detail : '';
    } else {
      detail = (await response.text().catch(() => '')).trim();
    }

    const suffix = detail ? `: ${detail.slice(0, 200)}` : '';
    throw new Error(`Upload failed (${response.status})${suffix}`);
  }
}

export async function confirmAssetUpload(projectId: string, assetId: string, token?: string | null): Promise<void> {
  await apiRequest<Record<string, unknown>>(`/v1/projects/${projectId}/assets/${assetId}:confirm-upload`, {
    method: 'POST',
  }, token);
}

export async function generateProject(
  projectId: string,
  input: {
    aspect_ratio: string;
    voice_style: string;
    voice_provider: string;
    voice_gender: string;
    language: string;
    background_music: string;
    idempotency_key?: string;
    // Phase 2
    script_template?: string;
    video_style?: string;
    transition_style?: string;
    caption_style?: string;
    show_title_card?: boolean;
    cta_text?: string;
    // Phase 3
    auto_approve?: boolean;
  },
  token?: string | null
): Promise<GenerationJob> {
  return apiRequest<GenerationJob>(`/v1/projects/${projectId}/generate`, {
    method: 'POST',
    body: JSON.stringify(input)
  }, token);
}

export async function getJob(jobId: string, token?: string | null): Promise<GenerationJob> {
  return apiRequest<GenerationJob>(`/v1/jobs/${jobId}`, {}, token);
}

export async function getProjectResult(projectId: string, jobId?: string, token?: string | null): Promise<VideoResult> {
  const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : '';
  return apiRequest<VideoResult>(`/v1/projects/${projectId}/result${query}`, {}, token);
}

export async function getProjectResults(projectId: string, token?: string | null): Promise<VideoResult[]> {
  return apiRequest<VideoResult[]>(`/v1/projects/${projectId}/results`, {}, token);
}

export async function translateProject(
  projectId: string,
  jobId: string,
  input: {
    target_languages: string[];
    voice_provider?: string;
    voice_gender?: string;
  },
  token?: string | null
): Promise<GenerationJob[]> {
  return apiRequest<GenerationJob[]>(`/v1/projects/${projectId}/jobs/${jobId}/translate`, {
    method: 'POST',
    body: JSON.stringify(input)
  }, token);
}

export async function getUsage(token?: string | null): Promise<UsageSummary> {
  return apiRequest<UsageSummary>('/v1/usage', {}, token);
}

export async function listProjects(token?: string | null): Promise<Project[]> {
  return apiRequest<Project[]>('/v1/projects', {}, token);
}

export async function listProjectJobs(projectId: string, token?: string | null): Promise<GenerationJob[]> {
  return apiRequest<GenerationJob[]>(`/v1/projects/${projectId}/jobs`, {}, token);
}

export interface AnalyticsEventInput {
  event_name: string;
  project_id?: string;
  job_id?: string;
  properties?: Record<string, unknown>;
}

export async function trackAnalyticsEvent(input: AnalyticsEventInput, token?: string | null): Promise<AnalyticsEventRecord> {
  return apiRequest<AnalyticsEventRecord>('/v1/analytics/events', {
    method: 'POST',
    body: JSON.stringify(input)
  }, token);
}

export async function listAnalyticsEvents(token?: string | null): Promise<AnalyticsEventRecord[]> {
  return apiRequest<AnalyticsEventRecord[]>('/v1/analytics/events', {}, token);
}

export async function getAdminOverview(token?: string | null): Promise<AdminOverview> {
  return apiRequest<AdminOverview>('/v1/admin/overview', {}, token);
}

export async function getAdminDeadLetters(token?: string | null): Promise<GenerationJob[]> {
  return apiRequest<GenerationJob[]>('/v1/admin/dead-letters', {}, token);
}

// ── Phase 3 — Feature A: Brand Kit & Asset Library ──────────────────────

export async function getBrandKit(token?: string | null): Promise<BrandKit> {
  return apiRequest<BrandKit>('/v1/brand-kit', {}, token);
}

export async function updateBrandKit(input: BrandKitInput, token?: string | null): Promise<BrandKit> {
  return apiRequest<BrandKit>('/v1/brand-kit', {
    method: 'PUT',
    body: JSON.stringify(input)
  }, token);
}

export async function listLibraryAssets(token?: string | null): Promise<LibraryAsset[]> {
  return apiRequest<LibraryAsset[]>('/v1/library/assets', {}, token);
}

export async function getLibraryAssetUploadUrl(
  input: LibraryAssetUploadInput,
  token?: string | null
): Promise<LibraryAssetUploadResponse> {
  return apiRequest<LibraryAssetUploadResponse>('/v1/library/assets', {
    method: 'POST',
    body: JSON.stringify(input)
  }, token);
}

export async function deleteLibraryAsset(assetId: string, token?: string | null): Promise<void> {
  await apiRequest<Record<string, string>>(`/v1/library/assets/${assetId}`, {
    method: 'DELETE'
  }, token);
}

// ── Phase 3 — Feature C: Social Media Distribution ──────────────────────

export async function generateMetadata(
  projectId: string,
  jobId: string,
  input: MetadataRequest,
  token?: string | null
): Promise<MetadataResponse> {
  return apiRequest<MetadataResponse>(
    `/v1/projects/${projectId}/jobs/${jobId}/metadata`,
    { method: 'POST', body: JSON.stringify(input) },
    token
  );
}

export async function listSocialConnections(token?: string | null): Promise<SocialConnection[]> {
  return apiRequest<SocialConnection[]>('/v1/social/connections', {}, token);
}

export async function disconnectSocial(connectionId: string, token?: string | null): Promise<void> {
  await apiRequest<Record<string, string>>(`/v1/social/connections/${connectionId}`, {
    method: 'DELETE'
  }, token);
}

export function getSocialOAuthUrl(platform: string): string {
  return `${API_BASE_URL}/v1/social/oauth/${platform}/authorize`;
}

export async function publishToYouTube(
  projectId: string,
  jobId: string,
  input: PublishRequest,
  token?: string | null
): Promise<PublishRecord> {
  return apiRequest<PublishRecord>(
    `/v1/projects/${projectId}/jobs/${jobId}/publish/youtube`,
    { method: 'POST', body: JSON.stringify(input) },
    token
  );
}

// ── Phase 3 — Feature D: Video Editor & Storyboard ─────────────────────

export async function getStoryboard(
  projectId: string,
  jobId: string,
  token?: string | null
): Promise<Storyboard> {
  return apiRequest<Storyboard>(
    `/v1/projects/${projectId}/jobs/${jobId}/storyboard`,
    {},
    token
  );
}

export async function updateStoryboard(
  projectId: string,
  jobId: string,
  scenes: StoryboardScene[],
  token?: string | null
): Promise<Storyboard> {
  return apiRequest<Storyboard>(
    `/v1/projects/${projectId}/jobs/${jobId}/storyboard`,
    { method: 'PUT', body: JSON.stringify({ scenes }) },
    token
  );
}

export async function approveStoryboard(
  projectId: string,
  jobId: string,
  token?: string | null
): Promise<GenerationJob> {
  return apiRequest<GenerationJob>(
    `/v1/projects/${projectId}/jobs/${jobId}/storyboard/approve`,
    { method: 'POST' },
    token
  );
}

export async function previewStoryboardAudio(
  projectId: string,
  jobId: string,
  token?: string | null
): Promise<{ audio_url: string }> {
  return apiRequest<{ audio_url: string }>(
    `/v1/projects/${projectId}/jobs/${jobId}/storyboard/preview-audio`,
    { method: 'POST' },
    token
  );
}

// ── Phase 3 — Feature E: A/B Video Variants ────────────────────────────

export async function generateVariants(
  projectId: string,
  input: GenerateVariantsInput,
  token?: string | null
): Promise<GenerationJob[]> {
  return apiRequest<GenerationJob[]>(
    `/v1/projects/${projectId}/generate-variants`,
    { method: 'POST', body: JSON.stringify(input) },
    token
  );
}

// ── Phase 4 — Editing Plan ─────────────────────────────────────────────

export async function getEditingPlan(
  projectId: string,
  jobId: string,
  token?: string | null
): Promise<Record<string, unknown>> {
  return apiRequest<Record<string, unknown>>(
    `/v1/projects/${projectId}/jobs/${jobId}/editing-plan`,
    {},
    token
  );
}
