# Phase 4 Development Plan — Remaining Integration Gaps

> **Status**: In Progress — Gap C complete
> **Created**: 2026-03-10
> **Scope**: Complete the 3 remaining gaps from the ShortGPT Integration Analysis

---

## Overview

Phase 1–3 implemented 11 of 14 ShortGPT integration recommendations. This plan covers the remaining 3 gaps, ordered by priority:

| Order | Gap | Priority | Effort | Impact |
|-------|-----|----------|--------|--------|
| 1 | C. LLM-Oriented Editing Framework | Medium | 3–4 weeks | 🟡 Medium — architectural unlock |
| 2 | A. Explicit Resumable Pipeline | Low | 3–4 days | � Polish — implicit resume already works |
| 3 | B. TikTok + Instagram Publishing | Medium | 6–8 weeks | 🟡 Medium — requires external API credentials |

> **Note on Gap A**: The current pipeline already caches intermediate artifacts per stage and
> skips completed stages on retry. Gap A adds an explicit `last_completed_stage` field and
> a dedicated resume endpoint — useful for observability and UX, but not functionally required.

---

## Gap A: Explicit Resumable Pipeline *(Deferred — Future Work)*

> **Status**: Deferred. The implicit artifact-based resume already works. This is a polish/observability improvement, not a functional requirement.

**Current state**: Pipeline stores intermediate artifacts per stage and reloads them on retry, but there is no explicit `last_completed_stage` field on the job record. Resume logic is implicit (check if artifact exists).

**Goal**: Make resume deterministic by tracking the last successfully completed stage on the job record, and allow the API to trigger resume from a specific stage.

### Tasks

#### A1. Add `last_completed_stage` field to job model
- **File**: `app/models.py`
- Add `last_completed_stage: str | None = None` to `JobRecord`
- Add `resume_from_stage: str | None = None` to `JobCreateParams` (for manual resume)

#### A2. Update repositories to persist `last_completed_stage`
- **Files**: `app/repositories/base.py`, `local.py`, `dynamo.py`
- `update_job()` already accepts kwargs — ensure `last_completed_stage` is stored/loaded

#### A3. Update pipeline to write `last_completed_stage` after each stage
- **File**: `app/services/pipeline.py`
- After each stage completes successfully (ANALYZING, SCRIPTING, MATCHING, NARRATION, RENDERING), call:
  ```python
  repo.update_job(job.id, last_completed_stage='ANALYZING')
  ```
- On pipeline entry, if `last_completed_stage` is set, skip all stages up to and including it (use artifact cache)

#### A4. Add resume endpoint
- **File**: `app/api/v1.py`
- `POST /v1/projects/{id}/jobs/{job_id}/resume` — re-enqueue a failed job, optionally with `resume_from_stage`
- Worker picks it up and skips completed stages

#### A5. Frontend: Add "Resume" button for failed jobs
- **File**: `apps/web/components/project-studio.tsx`
- Show "Resume from {stage}" button when a job has `status=failed` and `last_completed_stage` is set

#### A6. Tests
- **File**: `tests/test_phase4_resume.py`
- Test that `last_completed_stage` is persisted
- Test that pipeline skips stages when artifact exists and `last_completed_stage` is set
- Test resume endpoint creates a new job with correct `resume_from_stage`

**Estimate**: 3–4 days

---

## Gap B: TikTok + Instagram Publishing (Sprints 11–13)

**Current state**: YouTube OAuth + upload is fully implemented (`social/youtube.py`, `oauth.py`). The `social/base.py` abstract class exists. Metadata generation via LLM is done.

**Goal**: Add TikTok Content Posting API and Instagram Graph API publishing, plus a scheduling system.

### Sprint 11: TikTok Publishing (2 weeks)

#### B1. TikTok OAuth implementation
- **File**: `app/services/social/tiktok.py` (NEW)
- Implement `SocialPlatform` interface for TikTok
- TikTok Login Kit OAuth2 flow (Authorization Code)
- Token refresh handling
- Scopes: `video.upload`, `video.publish`

#### B2. TikTok video upload
- TikTok Content Posting API: `POST /v2/post/publish/video/init/` → chunk upload → publish
- Handle TikTok's async publish flow (video goes through review)
- Map NovaReel privacy settings to TikTok's: `PUBLIC_TO_EVERYONE`, `MUTUAL_FOLLOW_FRIENDS`, `SELF_ONLY`

#### B3. TikTok metadata mapping
- **File**: `app/services/metadata.py` — extend `generate_metadata()` to output TikTok-specific format
- Caption: max 150 chars
- Hashtags: auto-generated from product keywords
- Disclosure settings (branded content, paid partnership)

#### B4. Register TikTok in OAuth router
- **File**: `app/services/social/oauth.py` — add `tiktok` provider config
- **File**: `app/api/v1.py` — add TikTok to platform enum

#### B5. Frontend: TikTok connection + publish
- **File**: `apps/web/app/app/connections/page.tsx` — add TikTok to PLATFORMS array
- **File**: `apps/web/components/project-studio.tsx` — add TikTok option in publish modal

#### B6. Tests
- **File**: `tests/test_tiktok_social.py`
- Mock TikTok API responses for upload flow
- Test metadata character limits
- Test OAuth token refresh

**Prerequisites**: TikTok Developer account + app approval (can take 1–2 weeks)

### Sprint 12: Instagram Publishing (2 weeks)

#### B7. Instagram Graph API implementation
- **File**: `app/services/social/instagram.py` (NEW)
- Implement `SocialPlatform` interface for Instagram
- Instagram Graph API (via Facebook Login): Reels publishing flow
- Steps: Create media container → publish → check status
- Requires Facebook Business account linked to Instagram Professional account

#### B8. Instagram video upload
- Instagram Reels: `POST /{ig-user-id}/media` with `media_type=REELS`
- Handle the async creation container → status polling → publish flow
- Video requirements: MP4, H.264, max 90 seconds for Reels

#### B9. Instagram metadata mapping
- **File**: `app/services/metadata.py` — extend for Instagram format
- Caption: max 2200 chars
- Hashtags: up to 30
- Location tagging (optional)

#### B10. Register Instagram in OAuth router + Frontend
- Same pattern as TikTok: add to `oauth.py`, `v1.py`, connections page, publish modal

#### B11. Tests
- **File**: `tests/test_instagram_social.py`

**Prerequisites**: Facebook Developer account + Meta app review for `instagram_content_publish` permission

### Sprint 13: Publish Scheduling (2 weeks)

#### B12. Scheduling model
- **File**: `app/models.py` — add `ScheduledPublishRecord`:
  ```python
  class ScheduledPublishRecord(BaseModel):
      id: str
      owner_id: str
      job_id: str
      platform: str  # youtube | tiktok | instagram
      scheduled_at: datetime
      status: str  # pending | published | failed
      metadata: dict
  ```

#### B13. Scheduling endpoints
- **File**: `app/api/v1.py`:
  - `POST /v1/projects/{id}/jobs/{job_id}/schedule` — schedule a publish
  - `GET /v1/scheduled` — list scheduled publishes
  - `DELETE /v1/scheduled/{id}` — cancel scheduled publish

#### B14. Scheduler worker
- **File**: `app/services/social/scheduler.py` (NEW)
- Periodic task (Celery beat or polling) that checks for due `ScheduledPublishRecord` entries
- Publishes and updates status

#### B15. Frontend: Scheduling UI
- Add date/time picker to publish modal
- "Schedule" button alongside "Publish Now"
- Scheduled publishes list on a new `/app/scheduled` page

#### B16. Tests
- **File**: `tests/test_scheduler.py`

**Estimate**: 6 weeks total for Sprints 11–13

---

## Gap C: LLM-Oriented Editing Framework (Sprints 14–15)

**Current state**: Video rendering uses hardcoded FFmpeg commands in `video.py`. Effects are configured via `VideoEffectsConfig` dataclass. No JSON schema abstraction.

**Goal**: Introduce a JSON-based editing schema that decouples editing intent from rendering implementation, enabling future LLM-generated editing plans.

### Sprint 14: Schema + Interpreter (2 weeks)

#### C1. Define editing step JSON schema
- **File**: `app/services/editing/schema.py` (NEW)
- Pydantic models for editing steps:
  ```python
  class EditingStep(BaseModel):
      type: Literal['background_video', 'image_segment', 'text_overlay',
                     'transition', 'audio_track', 'logo_overlay', 'intro_outro']
      params: dict  # type-specific parameters

  class EditingPlan(BaseModel):
      version: str = '1.0'
      resolution: str
      fps: int = 30
      steps: list[EditingStep]
  ```

#### C2. Build plan compiler: EditingPlan → FFmpeg filter graph
- **File**: `app/services/editing/compiler.py` (NEW)
- Translate each step type into FFmpeg filter_complex fragments
- Compose fragments into a single render command
- Handles segment ordering, timing, layering

#### C3. Build plan generator: Job + Storyboard → EditingPlan
- **File**: `app/services/editing/planner.py` (NEW)
- Convert current pipeline output (storyboard + effects_config + audio paths) into an `EditingPlan` JSON
- This is the bridge: existing pipeline produces the plan, compiler renders it

#### C4. Integrate into video.py
- **File**: `app/services/video.py`
- Add a new render path: `render_from_plan(plan: EditingPlan) -> Path`
- Keep existing `render_video()` as fallback
- Feature flag: `use_editing_framework: bool = False` in settings

#### C5. Tests
- **File**: `tests/test_editing_framework.py`
- Test schema validation
- Test plan generation from a mock storyboard
- Test compiler produces valid FFmpeg commands (dry-run)

### Sprint 15: LLM-Driven Editing (2 weeks)

#### C6. LLM plan generation
- **File**: `app/services/editing/llm_planner.py` (NEW)
- Prompt the LLM with: product description + storyboard + available assets → JSON EditingPlan
- Validate LLM output against schema
- Fallback to deterministic planner if LLM output is invalid

#### C7. A/B testing: LLM vs deterministic plans
- Extend variants pipeline to optionally use LLM-generated editing plans for one variant and deterministic for another
- Compare output quality in UI

#### C8. Editing plan preview
- **File**: `app/api/v1.py` — `GET /v1/projects/{id}/jobs/{job_id}/editing-plan`
- Return the JSON plan for inspection/debugging
- Frontend: show plan as a timeline visualization (future)

#### C9. Frontend: Plan editor (stretch goal)
- Allow users to view and modify the editing plan before rendering
- JSON editor or drag-and-drop timeline (large effort, may be Phase 5)

**Estimate**: 3–4 weeks for Sprints 14–15

---

## Sprint Schedule

| Sprint | Duration | Focus | Dependencies |
|--------|----------|-------|-------------|
| 10 | 2 weeks | Gap C: Editing Schema + Interpreter | None |
| 11 | 2 weeks | Gap C: LLM-Driven Editing | Sprint 10 |
| 12 | 3–4 days | Gap A: Explicit Resumable Pipeline (optional) | None |
| 13 | 2 weeks | Gap B: TikTok Publishing | TikTok Developer account |
| 14 | 2 weeks | Gap B: Instagram Publishing | Facebook Developer account |
| 15 | 2 weeks | Gap B: Publish Scheduling | Sprints 13–14 |

**Total estimated duration**: ~10–11 weeks

---

## Environment / Credentials Required

| Item | Required For | How to Obtain |
|------|-------------|---------------|
| TikTok Developer App | Sprint 11 | https://developers.tiktok.com — requires app review |
| Facebook Developer App | Sprint 12 | https://developers.facebook.com — requires `instagram_content_publish` permission review |
| Meta Business Account | Sprint 12 | Must be linked to Instagram Professional account |

---

## Success Criteria

- [ ] Failed jobs show "Resume from {stage}" button and correctly skip completed stages
- [ ] Videos can be published to TikTok and Instagram directly from NovaReel
- [ ] Scheduled publishes execute at the configured time
- [ ] Editing plans are generated as JSON and rendered via the framework
- [ ] LLM can generate custom editing plans that produce valid videos
- [ ] All new features have test coverage
- [ ] ShortGPT Integration Analysis: 14/14 recommendations addressed
