import type { AdminOverview, AnalyticsEventRecord, GenerationJob, Project, UsageSummary, VideoResult } from '@/lib/contracts';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

type JsonObject = Record<string, unknown>;

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
  if (token) {
    mergedHeaders['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: mergedHeaders,
    body: file
  });

  if (!response.ok) {
    throw new Error(`Upload failed (${response.status})`);
  }
}

export async function generateProject(
  projectId: string,
  input: { aspect_ratio: string; voice_style: string; idempotency_key?: string },
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

export async function getProjectResult(projectId: string, token?: string | null): Promise<VideoResult> {
  return apiRequest<VideoResult>(`/v1/projects/${projectId}/result`, {}, token);
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
