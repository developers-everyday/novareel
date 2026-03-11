# NovaReel — Step-by-Step UI Testing Walkthrough

> Hands-on guide to set up your environment and test every UI feature.

---

## Step 1: Environment Variables Setup

### 1.1 Backend `.env`

Create the file at the **project root**:

```bash
cp .env.example .env
```

Open `.env` and verify these values are set:

```env
# ── REQUIRED for local testing ──────────────────────────────────────────

# Frontend URLs
NEXT_PUBLIC_APP_URL=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Auth — DISABLED for local testing (no Clerk account needed)
NOVAREEL_AUTH_DISABLED=true

# Storage & Queue — local mode, no AWS needed
NOVAREEL_STORAGE_BACKEND=local
NOVAREEL_QUEUE_BACKEND=poll

# AI — mock mode, no Bedrock/AWS credentials needed
NOVAREEL_USE_MOCK_AI=true

# Data storage location
NOVAREEL_LOCAL_DATA_DIR=services/backend/data

# API URL the worker uses to store output URLs
NOVAREEL_PUBLIC_API_BASE_URL=http://localhost:8000

# CORS — allow frontend
NOVAREEL_CORS_ORIGINS=["http://localhost:3000"]

# Admin user ID (matches the mock auth user)
NOVAREEL_ADMIN_USER_IDS=["beta-user"]

# Quota
NOVAREEL_MONTHLY_VIDEO_QUOTA=10

# ── OPTIONAL — only needed for specific features ────────────────────────

# TTS: Leave blank to use mock/Polly. Set for ElevenLabs premium voices.
NOVAREEL_ELEVENLABS_API_KEY=

# Stock footage: Set for real Pexels B-roll. Without it, B-roll is skipped.
NOVAREEL_PEXELS_API_KEY=

# YouTube publishing: Set for real OAuth flow. Without it, Connections page still renders.
NOVAREEL_GOOGLE_CLIENT_ID=
NOVAREEL_GOOGLE_CLIENT_SECRET=
NOVAREEL_SOCIAL_REDIRECT_BASE_URL=http://localhost:8000
NOVAREEL_ENCRYPTION_KEY=

# Rendering quality
NOVAREEL_FFMPEG_PRESET=medium

# Phase 4 editing framework (off by default)
NOVAREEL_USE_EDITING_FRAMEWORK=false
```

**Key point**: With the defaults above, **everything works out of the box** — no AWS, no Clerk, no external API keys. The app uses mock AI responses and local file storage.

### 1.2 Frontend `.env.local`

```bash
cp apps/web/.env.example apps/web/.env.local
```

Open `apps/web/.env.local` and set:

```env
NEXT_PUBLIC_APP_URL=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Clerk — use dummy values since auth is disabled on backend
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_placeholder
CLERK_SECRET_KEY=sk_test_placeholder
```

> **Note**: Clerk keys can be dummy values because `NOVAREEL_AUTH_DISABLED=true` on the backend makes the API accept all requests as user `beta-user`. The frontend Clerk components will show a "Sign in" button but you can navigate directly to `/app/dashboard` to bypass it.

---

## Step 2: Install Dependencies

### 2.1 Backend

```bash
cd services/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### 2.2 Frontend

```bash
cd apps/web
npm install
```

### 2.3 Verify ffmpeg (optional but recommended)

```bash
ffmpeg -version
```

- **If installed**: Videos will render with actual Ken-Burns zoom, transitions, audio, etc.
- **If missing**: Pipeline still completes but outputs placeholder bytes. Install with `brew install ffmpeg` (macOS).

---

## Step 3: Start the Application

You need **3 terminal windows** running simultaneously:

### Terminal 1 — API Server

```bash
cd services/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Verify**: Open http://localhost:8000/healthz in your browser.
You should see:
```json
{"status": "ok"}
```

Also open http://localhost:8000/docs — this is the Swagger UI with all API endpoints.

### Terminal 2 — Background Worker

```bash
cd services/backend
source .venv/bin/activate
python worker.py
```

You'll see:
```
INFO Worker started (queue_backend=poll)
```

> **Important**: The worker MUST be running for video generation to complete. Without it, jobs stay in "queued" status forever.

### Terminal 3 — Frontend

```bash
cd apps/web
npm run dev
```

**Verify**: Open http://localhost:3000 — you should see the NovaReel landing page.

---

## Step 4: Test the Landing Page

**URL**: http://localhost:3000

### What to check:
- [ ] Hero section loads: "Product photos to conversion-ready videos in under 2 minutes"
- [ ] "Start generating" button links to `/app/dashboard`
- [ ] "Explore features" button links to `/features`
- [ ] Three feature cards visible (Multimodal script intelligence, Nova 2 Sonic narration, Seller-ready output)
- [ ] Footer renders at bottom

### Navigation:
- [ ] Header has NovaReel logo
- [ ] Click "Start generating" → takes you to the dashboard

---

## Step 5: Test the Dashboard — Video Generation (Core Flow)

**URL**: http://localhost:3000/app/dashboard

> If Clerk shows a sign-in screen, navigate directly to `/app/dashboard`. With `AUTH_DISABLED=true`, the API accepts all requests.

### 5.1 Create & Generate a Video

1. **Fill in the form:**
   - **Product title**: `Wireless Bluetooth Speaker`
   - **Product description**: `Premium portable speaker with 20-hour battery, IPX7 waterproof, deep bass. Perfect for outdoor adventures and pool parties.`
   - **Aspect ratio**: `16:9 (landscape)`
   - **Voice style**: `Energetic`
   - **Voice engine**: `Amazon Polly (Default)`
   - **Voice gender**: `Female`
   - **Language**: `English`
   - **Background music**: `Auto (match voice style)`
   - **Script style**: `Product Showcase (Default)`
   - **Video style**: `Product Images Only (Default)`
   - **Caption style**: `No captions`
   - **Transition effect**: `Crossfade`
   - **Show title card**: Unchecked
   - **CTA text**: Leave empty
   - **Brand colors**: `#f97316,#0f172a` (default)

2. **Upload images:**
   - Click "Product images" file input
   - Select 3–5 JPEG/PNG images (any product photos, or use placeholder images)
   - Thumbnails should appear in the form

3. **Click "Generate video"**

### 5.2 Watch the Progress

- [ ] Button changes to "Preparing your generation job..."
- [ ] **Job Status Card** appears on the right panel showing current stage
- [ ] Status progresses through these stages (watch the worker terminal for logs):
  ```
  queued → analyzing → scripting → matching → narrating → rendering → completed
  ```
- [ ] Progress percentage updates in real-time (polls every 3 seconds)
- [ ] **Usage section** shows "Generated videos: 0" initially, then "1" after completion

### 5.3 View the Result

Once status shows **completed**:
- [ ] **Video player** appears with the rendered video
- [ ] Resolution and duration shown below the player (e.g., "1920x1080 · 30 sec")
- [ ] **Download MP4** button works
- [ ] **Download Transcript** button works
- [ ] **Download Subtitles** button works
- [ ] Three action buttons appear: **Translate** (blue), **Publish** (red), **A/B Variants** (purple)

### 5.4 Check Sidebar Panels

- [ ] **"Usage this month"** section shows updated count
- [ ] **"Current project jobs"** section lists the job with its ID and status
- [ ] **"Recent projects"** section lists the project with title and asset count

---

## Step 6: Test CSAT Feedback

After a video completes:
- [ ] **"Rate your first output"** section appears
- [ ] CSAT score dropdown: 1-5 (default: 5 - Excellent)
- [ ] Comment textarea visible
- [ ] Click **Submit feedback** → section disappears (CSAT sent successfully)

---

## Step 7: Test the Storyboard Editor

### 7.1 Enable Review Mode

1. Go back to the generation form
2. **Check** the "Review storyboard before rendering" checkbox
3. Fill in a new title and description (or reuse)
4. Upload images
5. Click **Generate video**

### 7.2 Edit & Approve

- [ ] Job pauses at **"awaiting_approval"** status (~50% progress)
- [ ] **"Edit Storyboard"** panel appears with editable scenes
- [ ] Each scene shows:
  - Scene number (circle badge)
  - Time range (e.g., "0.0s – 5.0s")
  - B-roll indicator if applicable
  - Editable script text (textarea)
- [ ] Edit a script line (change the text)
- [ ] Click **"Approve & Render"**
- [ ] Job resumes → progresses through remaining stages → completes

---

## Step 8: Test Video Translation

After a video completes:

1. Click the **Translate** button (blue)
2. **"Translate video"** panel appears

### What to check:
- [ ] Language grid shows 19 languages (all except English)
- [ ] Select 2-3 languages (e.g., Spanish, French, Japanese) — checkboxes toggle
- [ ] Voice engine dropdown: Edge TTS / Amazon Polly / ElevenLabs
- [ ] Voice gender dropdown: Female / Male
- [ ] Click **"Translate to 3 languages"** (button text updates with count)
- [ ] Translation jobs are created and appear in "Current project jobs"
- [ ] Cancel button hides the panel

---

## Step 9: Test YouTube Publish Modal

After a video completes:

1. Click the **Publish** button (red)
2. **"Publish to YouTube"** panel appears
3. It auto-generates metadata (shows "Generating metadata with AI..." briefly)

### What to check:
- [ ] Title field pre-populated with AI-generated title
- [ ] Description field pre-populated
- [ ] Tags field pre-populated (comma-separated)
- [ ] Privacy dropdown: Private / Unlisted / Public
- [ ] Edit any field → values update
- [ ] **Publish to YouTube** button is present (will fail without Google OAuth — expected)
- [ ] **Cancel** button hides the panel

> **Note**: Actual publishing requires `NOVAREEL_GOOGLE_CLIENT_ID` and `NOVAREEL_GOOGLE_CLIENT_SECRET`. Without them, metadata generation still works (mock mode), but publish will fail with an error.

---

## Step 10: Test A/B Variants

After a video completes:

1. Click the **A/B Variants** button (purple)
2. **"Generate A/B Variants"** panel appears

### What to check:
- [ ] Variant count dropdown: 2 / 3 / 4 / 5
- [ ] Select "3 variants"
- [ ] Click **"Generate 3 variants"**
- [ ] Multiple new jobs appear in "Current project jobs"
- [ ] Each variant processes independently through the pipeline
- [ ] Cancel button hides the panel

---

## Step 11: Test the Brand Kit Page

**URL**: http://localhost:3000/app/brand-kit

### 11.1 Brand Identity

- [ ] Page loads with heading "Brand Kit"
- [ ] **Brand name** input field
- [ ] **Three color pickers** (Primary, Secondary, Accent) with:
  - Color wheel input
  - Hex code text input
  - Color preview squares below
- [ ] Enter: Brand name = "TestBrand", Primary = `#FF5733`, Secondary = `#335BFF`, Accent = `#10B981`

### 11.2 Brand Assets

- [ ] **Upload logo** button (accepts images)
- [ ] **Upload font** button (accepts .ttf/.otf)
- [ ] **Upload intro** button (accepts .mp4)
- [ ] **Upload outro** button (accepts .mp4)
- [ ] Upload a logo image → shows filename under "Logo"
- [ ] Upload a font file → shows filename under "Custom font"

### 11.3 Save Brand Kit

- [ ] Click **"Save Brand Kit"** → success message appears: "Brand kit saved successfully."
- [ ] Refresh the page → all values should be preserved (loaded from API)

### 11.4 Asset Library

- [ ] Scroll to **"Asset Library"** section
- [ ] Lists all uploaded assets with filename, type, size, date
- [ ] **Delete** link next to each asset → removes it from the list
- [ ] **"Upload music or image asset"** button at bottom
- [ ] Upload an audio file → appears as "music" type
- [ ] Upload an image → appears as "image" type

---

## Step 12: Test the Connections Page

**URL**: http://localhost:3000/app/connections

### What to check:
- [ ] Page loads with heading "Social Connections"
- [ ] **YouTube** card shows "Not connected"
- [ ] **"Connect YouTube"** button (red) is visible
- [ ] Clicking "Connect YouTube" redirects to the OAuth URL (will fail without Google credentials — expected)
- [ ] If no connections exist, the "All Connections" section is hidden

> **To test with real YouTube**: Set `NOVAREEL_GOOGLE_CLIENT_ID` and `NOVAREEL_GOOGLE_CLIENT_SECRET` in `.env`, restart the API, and go through the Google OAuth flow.

---

## Step 13: Test the Admin Page

**URL**: http://localhost:3000/app/admin

### What to check:
- [ ] Page loads with heading "Admin Overview"
- [ ] Shows metrics:
  - Total projects
  - Total jobs
  - Completed jobs
  - Failed jobs
  - Active users
  - Dead-lettered jobs
- [ ] Numbers should reflect the projects/jobs you created during testing

---

## Step 14: Test Navigation

### Header Links (present on all `/app/*` pages):
- [ ] **NovaReel** logo → links to `/`
- [ ] **Dashboard** → links to `/app/dashboard`
- [ ] **Brand Kit** → links to `/app/brand-kit`
- [ ] **Connections** → links to `/app/connections`
- [ ] **Admin** → links to `/app/admin`
- [ ] **Pricing** → links to `/pricing`

### Public Pages:
- [ ] http://localhost:3000/ — Landing page
- [ ] http://localhost:3000/features — Features page
- [ ] http://localhost:3000/pricing — Pricing page

---

## Step 15: Test Different Generation Options

Create multiple projects with different settings to verify each option works:

### Test Matrix:

| Test | Setting | Value |
|------|---------|-------|
| A | Aspect ratio | `9:16 (vertical)` — verify resolution is 1080x1920 |
| B | Aspect ratio | `1:1 (square)` — verify resolution is 1080x1080 |
| C | Voice engine | `Edge TTS (Free)` — should complete without errors |
| D | Language | `Spanish (Español)` — script should reference Spanish |
| E | Script style | `Problem / Solution` — different script structure |
| F | Caption style | `Simple subtitles` — subtitles in output |
| G | Transition | `Slide left` — transitions between segments |
| H | Title card | Checked + CTA text "Shop now!" — overlays in video |
| I | Video style | `Product + Lifestyle B-Roll` — attempts Pexels fetch |

For each test:
1. Create a new project with the specific setting changed
2. Upload at least 1 image
3. Generate and wait for completion
4. Verify the result metadata (resolution, duration) matches expectations

---

## Step 16: Test Error Handling

### 16.1 Missing Required Fields
- [ ] Submit form with empty title → "Title and product description are required."
- [ ] Submit form with empty description → same error
- [ ] Submit form with no images → "Add at least one product image."

### 16.2 Worker Not Running
- [ ] Stop the worker (Ctrl+C in Terminal 2)
- [ ] Generate a video
- [ ] Job should stay in "queued" status (never progresses)
- [ ] Start the worker again → job should be picked up and processed

### 16.3 API Down
- [ ] Stop the API server (Ctrl+C in Terminal 1)
- [ ] Try any action in the UI → error messages should appear in red banners
- [ ] Start the API again → UI should recover on next action

---

## Step 17: Test the Swagger API Docs

**URL**: http://localhost:8000/docs

### What to check:
- [ ] Page loads with interactive Swagger UI
- [ ] All endpoint groups visible: projects, jobs, brand kit, library, social, analytics, admin
- [ ] Try executing `GET /healthz` → returns `{"status": "ok"}`
- [ ] Try executing `GET /v1/projects` → returns your created projects
- [ ] Try executing `GET /v1/usage` → returns usage summary

---

## Step 18: Test Phase 4 — Editing Framework (Optional)

### Enable the Framework:

1. Edit `.env`: set `NOVAREEL_USE_EDITING_FRAMEWORK=true`
2. Restart the API server and worker
3. Generate a video as normal

### What to check:
- [ ] Video generates successfully (same as without the framework)
- [ ] In Swagger, call `GET /v1/projects/{project_id}/jobs/{job_id}/editing-plan`
- [ ] Response should be a JSON editing plan with:
  - `version`: "1.0"
  - `resolution`: matches aspect ratio
  - `steps`: array of segment and post-processing steps
- [ ] Disable it again: set `NOVAREEL_USE_EDITING_FRAMEWORK=false` and restart

---

## Quick Reset

If you want to start fresh and clear all data:

```bash
rm -rf services/backend/data
```

Restart the API and worker. All projects, jobs, and assets will be cleared.

---

## Summary Checklist

| Page | URL | Key Tests |
|------|-----|-----------|
| Landing | `/` | Hero, feature cards, navigation links |
| Features | `/features` | Static content renders |
| Pricing | `/pricing` | Static content renders |
| Dashboard | `/app/dashboard` | Full generation flow, storyboard editor, translate, publish, variants, CSAT |
| Brand Kit | `/app/brand-kit` | Brand identity, color pickers, asset upload/delete, save/load |
| Connections | `/app/connections` | YouTube card, connect/disconnect buttons |
| Admin | `/app/admin` | Metrics display |
| API Docs | `:8000/docs` | Swagger interactive testing |
