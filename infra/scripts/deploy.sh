#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
# NovaReel — Build, Push, and Deploy to AWS
# ─────────────────────────────────────────────
# Usage:
#   ./infra/scripts/deploy.sh                  # deploy all (default: production)
#   ./infra/scripts/deploy.sh --env staging    # deploy to staging
#   ./infra/scripts/deploy.sh --skip-build     # redeploy without rebuilding images
#   ./infra/scripts/deploy.sh --infra-only     # deploy CloudFormation only
# ─────────────────────────────────────────────

ENVIRONMENT="production"
SKIP_BUILD=false
INFRA_ONLY=false
AWS_REGION="${AWS_REGION:-us-east-1}"
STACK_NAME=""
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --env) ENVIRONMENT="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --infra-only) INFRA_ONLY=true; shift ;;
    --region) AWS_REGION="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

STACK_NAME="novareel-${ENVIRONMENT}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
API_ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/novareel-${ENVIRONMENT}-api"
WORKER_ECR_REPO="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/novareel-${ENVIRONMENT}-worker"
IMAGE_TAG="$(git rev-parse --short HEAD)-$(date +%s)"
PARAMETER_OVERRIDES=("Environment=${ENVIRONMENT}")

if [[ -n "${CLERK_PUBLISHABLE_KEY:-}" ]]; then
  PARAMETER_OVERRIDES+=("ClerkPublishableKey=${CLERK_PUBLISHABLE_KEY}")
fi
if [[ -n "${NOVAREEL_CLERK_JWKS_URL:-}" ]]; then
  PARAMETER_OVERRIDES+=("ClerkJwksUrl=${NOVAREEL_CLERK_JWKS_URL}")
fi
if [[ -n "${NOVAREEL_CLERK_ISSUER:-}" ]]; then
  PARAMETER_OVERRIDES+=("ClerkIssuer=${NOVAREEL_CLERK_ISSUER}")
fi
if [[ -n "${NOVAREEL_CLERK_AUDIENCE:-}" ]]; then
  PARAMETER_OVERRIDES+=("ClerkAudience=${NOVAREEL_CLERK_AUDIENCE}")
fi
if [[ -n "${CLERK_SECRET_KEY:-}" ]]; then
  PARAMETER_OVERRIDES+=("ClerkSecretKey=${CLERK_SECRET_KEY}")
fi
if [[ -n "${NOVAREEL_PEXELS_API_KEY:-}" ]]; then
  PARAMETER_OVERRIDES+=("PexelsApiKey=${NOVAREEL_PEXELS_API_KEY}")
fi
if [[ -n "${NOVAREEL_ELEVENLABS_API_KEY:-}" ]]; then
  PARAMETER_OVERRIDES+=("ElevenlabsApiKey=${NOVAREEL_ELEVENLABS_API_KEY}")
fi
if [[ -n "${NOVAREEL_GOOGLE_CLIENT_ID:-}" ]]; then
  PARAMETER_OVERRIDES+=("GoogleClientId=${NOVAREEL_GOOGLE_CLIENT_ID}")
fi
if [[ -n "${NOVAREEL_GOOGLE_CLIENT_SECRET:-}" ]]; then
  PARAMETER_OVERRIDES+=("GoogleClientSecret=${NOVAREEL_GOOGLE_CLIENT_SECRET}")
fi
if [[ -n "${NOVAREEL_ENCRYPTION_KEY:-}" ]]; then
  PARAMETER_OVERRIDES+=("EncryptionKey=${NOVAREEL_ENCRYPTION_KEY}")
fi
if [[ -n "${NOVAREEL_SOCIAL_REDIRECT_BASE_URL:-}" ]]; then
  PARAMETER_OVERRIDES+=("SocialRedirectBaseUrl=${NOVAREEL_SOCIAL_REDIRECT_BASE_URL}")
fi
if [[ -n "${NOVAREEL_CORS_ORIGIN:-}" ]]; then
  PARAMETER_OVERRIDES+=("CorsOrigin=${NOVAREEL_CORS_ORIGIN}")
fi
if [[ -n "${NOVAREEL_FRONTEND_URL:-}" ]]; then
  PARAMETER_OVERRIDES+=("FrontendUrl=${NOVAREEL_FRONTEND_URL}")
fi

echo "╔══════════════════════════════════════════╗"
echo "║  NovaReel Deploy                         ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Environment : ${ENVIRONMENT}"
echo "║  Region      : ${AWS_REGION}"
echo "║  Account     : ${AWS_ACCOUNT_ID}"
echo "║  Platform    : ${DOCKER_PLATFORM}"
echo "║  Image Tag   : ${IMAGE_TAG}"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Step 1: Deploy Infrastructure ──────────
echo "▶ Step 1: Deploying CloudFormation stack '${STACK_NAME}'..."

# Check if stack exists, if not create without image URIs first
STACK_EXISTS=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" --region "${AWS_REGION}" 2>&1 || true)

if echo "${STACK_EXISTS}" | grep -q "does not exist"; then
  echo "  Stack does not exist — creating infrastructure (ECR repos, DynamoDB, S3, SQS, etc.)..."
  aws cloudformation deploy \
    --template-file "${PROJECT_ROOT}/infra/cloudformation.yml" \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "${PARAMETER_OVERRIDES[@]}" \
    --no-fail-on-empty-changeset
  echo "  ✔ Infrastructure stack created."
else
  echo "  Stack already exists — updating infrastructure..."
  aws cloudformation deploy \
    --template-file "${PROJECT_ROOT}/infra/cloudformation.yml" \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "${PARAMETER_OVERRIDES[@]}" \
    --no-fail-on-empty-changeset
  echo "  ✔ Infrastructure stack updated."
fi

if [ "$INFRA_ONLY" = true ]; then
  echo ""
  echo "✔ Infrastructure-only deploy complete."
  aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" --query 'Stacks[0].Outputs' --output table
  exit 0
fi

# ── Step 2: Build Docker Images ────────────
if [ "$SKIP_BUILD" = false ]; then
  echo ""
  echo "▶ Step 2: Building Docker images..."

  echo "  Building API image..."
  docker build \
    --platform "${DOCKER_PLATFORM}" \
    -f "${PROJECT_ROOT}/infra/docker/Dockerfile.api" \
    -t "${API_ECR_REPO}:${IMAGE_TAG}" \
    -t "${API_ECR_REPO}:latest" \
    "${PROJECT_ROOT}"

  echo "  Building Worker image..."
  docker build \
    --platform "${DOCKER_PLATFORM}" \
    -f "${PROJECT_ROOT}/infra/docker/Dockerfile.worker" \
    -t "${WORKER_ECR_REPO}:${IMAGE_TAG}" \
    -t "${WORKER_ECR_REPO}:latest" \
    "${PROJECT_ROOT}"

  echo "  ✔ Docker images built."

  # ── Step 3: Push to ECR ──────────────────
  echo ""
  echo "▶ Step 3: Pushing images to ECR..."

  aws ecr get-login-password --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

  docker push "${API_ECR_REPO}:${IMAGE_TAG}"
  docker push "${API_ECR_REPO}:latest"
  docker push "${WORKER_ECR_REPO}:${IMAGE_TAG}"
  docker push "${WORKER_ECR_REPO}:latest"

  echo "  ✔ Images pushed."
else
  echo ""
  echo "▶ Step 2-3: Skipping build/push (--skip-build)"
  IMAGE_TAG="latest"
fi

# ── Step 4: Update CloudFormation with Image URIs ──
echo ""
echo "▶ Step 4: Updating stack with image URIs..."

IMAGE_PARAMETER_OVERRIDES=("${PARAMETER_OVERRIDES[@]}")
IMAGE_PARAMETER_OVERRIDES+=("ApiImageUri=${API_ECR_REPO}:${IMAGE_TAG}")
IMAGE_PARAMETER_OVERRIDES+=("WorkerImageUri=${WORKER_ECR_REPO}:${IMAGE_TAG}")

aws cloudformation deploy \
  --template-file "${PROJECT_ROOT}/infra/cloudformation.yml" \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "${IMAGE_PARAMETER_OVERRIDES[@]}" \
  --no-fail-on-empty-changeset

echo "  ✔ ECS services updated."

# ── Step 5: Wait for Services to Stabilize ──
echo ""
echo "▶ Step 5: Waiting for ECS services to stabilize..."

CLUSTER_NAME=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" --query 'Stacks[0].Outputs[?OutputKey==`ECSClusterName`].OutputValue' --output text)

aws ecs wait services-stable \
  --cluster "${CLUSTER_NAME}" \
  --services "novareel-${ENVIRONMENT}-api" "novareel-${ENVIRONMENT}-worker" \
  --region "${AWS_REGION}" 2>/dev/null || echo "  ⚠ Timeout waiting for stability (services may still be rolling out)"

echo "  ✔ Services stable."

# ── Step 6: Print Outputs ──────────────────
echo ""
echo "▶ Step 6: Stack outputs:"
echo ""
aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" --query 'Stacks[0].Outputs' --output table

# ── Health Check ───────────────────────────
ALB_URL=$(aws cloudformation describe-stacks --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" --query 'Stacks[0].Outputs[?OutputKey==`ALBURL`].OutputValue' --output text)

echo ""
echo "▶ Health check: ${ALB_URL}/healthz"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "${ALB_URL}/healthz" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  echo "  ✔ API is healthy!"
else
  echo "  ⚠ Health check returned HTTP ${HTTP_CODE} (service may still be starting)"
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✔ Deployment Complete                   ║"
echo "╚══════════════════════════════════════════╝"
