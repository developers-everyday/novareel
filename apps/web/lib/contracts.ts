export type JobStatus =
  | 'queued'
  | 'scripting'
  | 'matching'
  | 'narration'
  | 'rendering'
  | 'completed'
  | 'failed';

export interface Project {
  id: string;
  owner_id: string;
  title: string;
  product_description: string;
  brand_prefs: Record<string, string | string[]>;
  created_at: string;
  asset_ids: string[];
}

export interface GenerationJob {
  id: string;
  project_id: string;
  owner_id: string;
  status: JobStatus;
  stage: JobStatus;
  progress_pct: number;
  error_code: string | null;
  timings: Record<string, number>;
  created_at: string;
  updated_at: string;
  aspect_ratio?: string;
  voice_style?: string;
  idempotency_key?: string | null;
  attempt_count?: number;
  max_attempts?: number;
  next_attempt_at?: string | null;
  dead_lettered?: boolean;
  dead_letter_reason?: string | null;
}

export interface VideoResult {
  project_id: string;
  video_s3_key: string;
  video_url: string;
  duration_sec: number;
  resolution: string;
  thumbnail_key: string | null;
  transcript_key: string | null;
  transcript_url?: string | null;
  subtitle_key?: string | null;
  subtitle_url?: string | null;
}

export interface UsageSummary {
  owner_id: string;
  month: string;
  videos_generated: number;
  quota_limit: number;
  remaining: number;
}

export interface AnalyticsEventRecord {
  id: string;
  owner_id: string;
  event_name: string;
  project_id: string | null;
  job_id: string | null;
  properties: Record<string, unknown>;
  created_at: string;
}

export interface AdminOverview {
  month: string;
  active_creators: number;
  activated_creators: number;
  activation_rate_pct: number;
  total_projects: number;
  total_jobs: number;
  successful_jobs: number;
  failed_jobs: number;
  dead_letter_jobs: number;
  videos_generated: number;
  recent_jobs: GenerationJob[];
  recent_events: AnalyticsEventRecord[];
}
