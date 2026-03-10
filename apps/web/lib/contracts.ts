export type JobStatus =
  | 'queued'
  | 'analyzing'
  | 'scripting'
  | 'matching'
  | 'narration'
  | 'rendering'
  | 'completed'
  | 'failed'
  | 'loading'
  | 'translating'
  | 'awaiting_approval';

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
  voice_provider?: string;
  voice_gender?: string;
  language?: string;
  background_music?: string;
  idempotency_key?: string | null;
  attempt_count?: number;
  max_attempts?: number;
  next_attempt_at?: string | null;
  dead_lettered?: boolean;
  dead_letter_reason?: string | null;
  last_completed_stage?: string | null;
  // Phase 2
  job_type?: string;
  source_job_id?: string | null;
  script_template?: string;
  video_style?: string;
  transition_style?: string;
  caption_style?: string;
  show_title_card?: boolean;
  cta_text?: string | null;
  // Phase 3
  auto_approve?: boolean;
  variant_group_id?: string | null;
}

export interface VideoResult {
  project_id: string;
  job_id?: string;
  video_s3_key: string;
  video_url: string;
  duration_sec: number;
  resolution: string;
  thumbnail_key: string | null;
  transcript_key: string | null;
  transcript_url?: string | null;
  subtitle_key?: string | null;
  subtitle_url?: string | null;
  script_lines?: string[];
  language?: string;
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

// ── Phase 3 — Feature A: Brand Kit & Asset Library ──────────────────────

export interface BrandKit {
  owner_id: string;
  brand_name: string;
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  logo_asset_id: string | null;
  font_asset_id: string | null;
  intro_clip_asset_id: string | null;
  outro_clip_asset_id: string | null;
  custom_music_asset_ids: string[];
  updated_at: string;
}

export interface BrandKitInput {
  brand_name?: string;
  primary_color?: string;
  secondary_color?: string;
  accent_color?: string;
  logo_asset_id?: string | null;
  font_asset_id?: string | null;
  intro_clip_asset_id?: string | null;
  outro_clip_asset_id?: string | null;
  custom_music_asset_ids?: string[];
}

export interface LibraryAsset {
  id: string;
  owner_id: string;
  asset_type: 'logo' | 'font' | 'intro_clip' | 'outro_clip' | 'music' | 'image';
  filename: string;
  content_type: string;
  file_size: number;
  object_key: string;
  created_at: string;
}

export interface LibraryAssetUploadInput {
  filename: string;
  asset_type: 'logo' | 'font' | 'intro_clip' | 'outro_clip' | 'music' | 'image';
  content_type: string;
  file_size: number;
}

export interface LibraryAssetUploadResponse {
  asset_id: string;
  object_key: string;
  upload_url: string;
  method: 'PUT';
  headers: Record<string, string>;
}

// ── Phase 3 — Feature C: Social Media Distribution ──────────────────────

export interface MetadataRequest {
  platforms: ('youtube' | 'tiktok' | 'instagram')[];
  product_keywords?: string[];
}

export interface MetadataResponse {
  youtube?: Record<string, unknown>;
  tiktok?: Record<string, unknown>;
  instagram?: Record<string, unknown>;
}

export interface SocialConnection {
  id: string;
  owner_id: string;
  platform: 'youtube' | 'tiktok' | 'instagram';
  platform_user_id: string;
  platform_username: string;
  token_expires_at: string;
  connected_at: string;
}

export interface PublishRequest {
  title: string;
  description?: string;
  tags?: string[];
  category?: string;
  privacy?: 'public' | 'unlisted' | 'private';
}

export interface PublishRecord {
  id: string;
  owner_id: string;
  job_id: string;
  platform: string;
  platform_video_id: string;
  platform_url: string;
  metadata_used: Record<string, unknown>;
  published_at: string;
}

// ── Phase 3 — Feature D: Video Editor & Storyboard ─────────────────────

export interface StoryboardScene {
  order: number;
  script_line: string;
  image_asset_id: string;
  start_sec: number;
  duration_sec: number;
  media_type?: 'image' | 'video';
  video_path?: string | null;
}

export interface Storyboard {
  job_id: string;
  project_id: string;
  scenes: StoryboardScene[];
  status: string;
}

// ── Phase 3 — Feature E: A/B Video Variants ────────────────────────────

export interface GenerateVariantsInput {
  variant_count?: number;
  shared?: Record<string, unknown>;
  overrides?: Record<string, unknown>[];
}
