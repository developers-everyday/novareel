# NovaReel — AWS Deployment Plan

> **Date:** March 2026  
> **Stack:** Next.js 14 (frontend) · FastAPI + Python 3.12 (backend API & worker) · Redis · ffmpeg  
> **Target Cloud:** AWS (us-east-1)

---

## 1. Architecture Overview

```
                        ┌──────────────┐
                        │  CloudFront  │
                        │   (CDN)      │
                        └──────┬───────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
     ┌────────────────┐ ┌───────────┐  ┌──────────────┐
     │  Amplify / S3  │ │    ALB    │  │  S3 (assets) │
     │  (Next.js SSR) │ │           │  │              │
     └────────────────┘ └─────┬─────┘  └──────────────┘
                              │
                 ┌────────────┼────────────┐
                 ▼                         ▼
        ┌────────────────┐       ┌─────────────────┐
        │  ECS Fargate   │       │  ECS Fargate    │
        │  (API Service) │       │  (Worker Svc)   │
        └───────┬────────┘       └────────┬────────┘
                │                         │
     ┌──────────┼──────────┐    ┌─────────┼──────────┐
     ▼          ▼          ▼    ▼         ▼          ▼
  DynamoDB   Bedrock     SQS  S3     ElastiCache  Bedrock
                                      (Redis)
```

### Services Used

| AWS Service | Purpose |
|---|---|
| **ECS Fargate** | Run API containers + Worker containers (no EC2 to manage) |
| **ECR** | Docker image registry |
| **ALB** | Load balancer for API service |
| **DynamoDB** | Projects, Jobs, Results, Usage, Analytics tables |
| **S3** | Asset storage (uploads, generated videos, audio, thumbnails) |
| **SQS** | Job queue (replaces polling mode) |
| **ElastiCache (Redis)** | Celery broker (optional; or use SQS-only mode) |
| **CloudFront** | CDN for generated video assets + frontend |
| **Bedrock** | Nova Lite, Nova Pro, Nova Sonic, Nova Canvas models |
| **AWS Amplify** | Next.js SSR hosting (or containerized on ECS) |
| **Secrets Manager** | API keys, Clerk keys, encryption key |
| **CloudWatch** | Logs, metrics, alarms |
| **Route 53** | DNS (optional, custom domain) |
| **ACM** | TLS certificates |

---

## 2. Component Deployment Strategy

### 2.1 Frontend — Next.js (AWS Amplify)

- **Method:** AWS Amplify Hosting (supports Next.js SSR natively)
- **Build:** `npm run build` produces `.next/` output
- **Environment variables:** `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_APP_URL`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`
- **Custom domain:** Configure in Amplify → Route 53

**Alternative:** Build a Docker image and run on ECS Fargate behind the same ALB (path-based routing: `/` → frontend, `/v1/*` → API). This approach is used in the CloudFormation template below.

### 2.2 Backend API — FastAPI (ECS Fargate)

- **Image:** `Dockerfile.api` → Python 3.12 slim + ffmpeg + pip install
- **Port:** 8000
- **Health check:** `GET /healthz`
- **Scaling:** Min 1, Max 4 tasks (CPU-based auto-scaling)
- **Key env vars:**
  - `NOVAREEL_STORAGE_BACKEND=dynamodb`
  - `NOVAREEL_QUEUE_BACKEND=sqs`
  - `NOVAREEL_AUTH_DISABLED=false`
  - `NOVAREEL_USE_MOCK_AI=false`
  - `NOVAREEL_CDN_BASE_URL=https://d1234.cloudfront.net`

### 2.3 Worker — Python (ECS Fargate)

- **Image:** `Dockerfile.worker` (same base, different entrypoint)
- **Entrypoint:** `python worker.py` (SQS polling mode)
- **Scaling:** Min 1, Max 8 tasks (SQS queue depth auto-scaling)
- **Needs:** ffmpeg installed for video rendering
- **CPU/Memory:** 1 vCPU / 4 GB (video processing is memory-heavy)

### 2.4 Database — DynamoDB

| Table | Partition Key | Sort Key | Purpose |
|---|---|---|---|
| `novareel-projects` | `owner_id` | `id` | Project records |
| `novareel-jobs` | `project_id` | `id` | Generation/translation jobs |
| `novareel-results` | `job_id` | — | Completed job results |
| `novareel-usage` | `owner_id` | `period` | Monthly usage tracking |
| `novareel-analytics` | `owner_id` | `timestamp#event` | Analytics events |

All tables use **on-demand** billing (no capacity planning needed).

### 2.5 Storage — S3

- **Bucket:** `novareel-phase1` (or custom)
- **Structure:** `projects/{project_id}/{asset_type}/{filename}`
- **Lifecycle:** 90-day transition to S3 IA for old project assets
- **CORS:** Allow frontend origin

### 2.6 Queue — SQS

- **Queue:** `novareel-jobs` (standard queue)
- **Visibility timeout:** 900s (15 min, for long video generation)
- **Dead-letter queue:** `novareel-jobs-dlq` (maxReceiveCount: 3)
- **Delay:** Supports per-message delay for retry backoff

### 2.7 CDN — CloudFront

- **Distribution origins:**
  - S3 bucket (generated assets)
  - ALB (API, if needed)
- **Behaviors:** Cache assets aggressively, no caching for API calls
- **OAC:** Origin Access Control for S3

---

## 3. Infrastructure as Code

All infrastructure is defined in `infra/cloudformation.yml` (see file). Key resources:

- VPC with 2 public + 2 private subnets
- ECS Cluster + Fargate services (API + Worker)
- ALB + Target Group + Listener
- DynamoDB tables (5)
- S3 bucket + CloudFront distribution
- SQS queue + DLQ
- ECR repositories
- IAM roles & policies
- CloudWatch log groups
- Secrets Manager secret

---

## 4. Docker Images

Two images share a common base:

```
infra/
  docker/
    Dockerfile.api       # API server (uvicorn)
    Dockerfile.worker    # Job processing worker
    .dockerignore
```

Both install the same Python package; they differ only in `CMD`.

---

## 5. Deployment Pipeline

### 5.1 CI/CD Flow (GitHub Actions)

```
push to main
  ├─ test (existing CI)
  ├─ build-and-push (Docker → ECR)
  └─ deploy
       ├─ Update ECS API service
       ├─ Update ECS Worker service
       └─ Trigger Amplify build (frontend)
```

### 5.2 Deployment Script

`infra/scripts/deploy.sh` automates:
1. Build Docker images
2. Push to ECR
3. Update ECS services (rolling deployment)

---

## 6. Environment Configuration

### Production Environment Variables

```bash
# Core
NOVAREEL_ENV=production
NOVAREEL_AUTH_DISABLED=false
NOVAREEL_USE_MOCK_AI=false

# Storage
NOVAREEL_STORAGE_BACKEND=dynamodb
NOVAREEL_QUEUE_BACKEND=sqs

# AWS
NOVAREEL_AWS_REGION=us-east-1
NOVAREEL_S3_BUCKET_NAME=novareel-prod
NOVAREEL_DYNAMODB_PROJECTS_TABLE=novareel-projects
NOVAREEL_DYNAMODB_JOBS_TABLE=novareel-jobs
NOVAREEL_DYNAMODB_RESULTS_TABLE=novareel-results
NOVAREEL_DYNAMODB_USAGE_TABLE=novareel-usage
NOVAREEL_DYNAMODB_ANALYTICS_TABLE=novareel-analytics
NOVAREEL_SQS_QUEUE_URL=<from CloudFormation output>

# CDN
NOVAREEL_CDN_BASE_URL=<CloudFront distribution URL>

# Auth
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=<clerk_pk>
CLERK_SECRET_KEY=<from Secrets Manager>

# Bedrock (models)
NOVAREEL_BEDROCK_MODEL_SCRIPT=amazon.nova-lite-v1:0
NOVAREEL_BEDROCK_MODEL_ORCHESTRATOR=amazon.nova-pro-v1:0
NOVAREEL_BEDROCK_MODEL_VOICE=amazon.nova-sonic-v1:0
NOVAREEL_BEDROCK_MODEL_IMAGE=amazon.nova-canvas-v1:0

# Performance
NOVAREEL_WORKER_MODE=polling
NOVAREEL_FFMPEG_PRESET=medium
NOVAREEL_CORS_ORIGINS=["https://novareel.example.com"]
```

---

## 7. Security

- **IAM:** Least-privilege task roles (Bedrock invoke, DynamoDB CRUD, S3 read/write, SQS send/receive)
- **Secrets:** All API keys in AWS Secrets Manager, injected as ECS container secrets
- **Network:** API in private subnet behind ALB; worker in private subnet
- **TLS:** ACM certificate on ALB + CloudFront
- **Auth:** Clerk JWT validation enabled in production (`AUTH_DISABLED=false`)
- **S3:** Block public access; CloudFront OAC for asset delivery
- **DynamoDB:** Encryption at rest (default)

---

## 8. Monitoring & Alerting

| Metric | Alarm Threshold | Action |
|---|---|---|
| API 5xx rate | > 5% over 5 min | SNS → PagerDuty/email |
| SQS queue depth | > 50 messages for 10 min | Scale workers |
| SQS DLQ depth | > 0 | SNS alert |
| ECS CPU utilization | > 70% sustained 5 min | Auto-scale |
| DynamoDB throttles | > 0 | Review capacity / switch to provisioned |
| Worker task failures | > 10% | SNS alert |

CloudWatch Logs:
- `/novareel/api` — API container logs
- `/novareel/worker` — Worker container logs

---

## 9. Cost Estimate (small-scale)

| Resource | Config | Est. Monthly Cost |
|---|---|---|
| ECS Fargate (API) | 1 task × 0.5 vCPU / 1 GB | ~$15 |
| ECS Fargate (Worker) | 1 task × 1 vCPU / 4 GB | ~$55 |
| DynamoDB (on-demand) | Low traffic | ~$5 |
| S3 (100 GB) | Standard | ~$3 |
| SQS | Low traffic | < $1 |
| CloudFront | 100 GB transfer | ~$9 |
| ALB | 1 ALB | ~$20 |
| ElastiCache (optional) | t3.micro | ~$13 |
| ECR | Image storage | < $1 |
| Bedrock | Pay-per-token | Variable |
| **Total (excl. Bedrock)** | | **~$120/mo** |

---

## 10. Deployment Steps (First Time)

### Prerequisites
- AWS CLI configured with appropriate credentials
- Docker installed
- GitHub repo secrets configured for CI/CD

### Step-by-step

```bash
# 1. Deploy CloudFormation stack
aws cloudformation deploy \
  --template-file infra/cloudformation.yml \
  --stack-name novareel-prod \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    Environment=production \
    ClerkSecretKey=<your-clerk-secret> \
    PexelsApiKey=<your-pexels-key>

# 2. Get stack outputs
aws cloudformation describe-stacks --stack-name novareel-prod \
  --query 'Stacks[0].Outputs' --output table

# 3. Build and push Docker images
./infra/scripts/deploy.sh

# 4. Deploy frontend to Amplify
# (connect GitHub repo in Amplify console, or use amplify CLI)

# 5. Verify
curl https://api.novareel.example.com/healthz
```

### Post-deploy Checklist
- [ ] Verify `/healthz` returns `{"status": "ok"}`
- [ ] Verify Clerk auth works (test protected endpoints)
- [ ] Submit a test generation job; confirm SQS → worker → S3
- [ ] Verify CloudFront serves generated video
- [ ] Check CloudWatch logs for errors
- [ ] Run phase1_runbook.md operator checklist

---

## 11. Rollback

- **ECS:** Previous task definition is always available; rollback via `aws ecs update-service --force-new-deployment` with prior task def
- **CloudFormation:** `aws cloudformation rollback-stack --stack-name novareel-prod`
- **Emergency:** Set `NOVAREEL_USE_MOCK_AI=true` to disable Bedrock dependency
- **Frontend:** Amplify supports instant rollback to previous deployment

---

## 12. File Inventory (created by this plan)

```
infra/
  cloudformation.yml           # Full AWS infrastructure
  docker/
    Dockerfile.api             # API server image
    Dockerfile.worker          # Worker image
    .dockerignore              # Docker build exclusions
  scripts/
    deploy.sh                  # Build, push, deploy script
.github/
  workflows/
    deploy.yml                 # CD pipeline (GitHub Actions)
```
