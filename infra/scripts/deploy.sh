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

echo "╔══════════════════════════════════════════╗"
echo "║  NovaReel Deploy                         ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Environment : ${ENVIRONMENT}"
echo "║  Region      : ${AWS_REGION}"
echo "║  Account     : ${AWS_ACCOUNT_ID}"
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
    --parameter-overrides \
      Environment="${ENVIRONMENT}" \
    --no-fail-on-empty-changeset
  echo "  ✔ Infrastructure stack created."
else
  echo "  Stack already exists — updating infrastructure..."
  aws cloudformation deploy \
    --template-file "${PROJECT_ROOT}/infra/cloudformation.yml" \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --capabilities CAPABILITY_NAMED_IAM \
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
    -f "${PROJECT_ROOT}/infra/docker/Dockerfile.api" \
    -t "${API_ECR_REPO}:${IMAGE_TAG}" \
    -t "${API_ECR_REPO}:latest" \
    "${PROJECT_ROOT}"

  echo "  Building Worker image..."
  docker build \
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

aws cloudformation deploy \
  --template-file "${PROJECT_ROOT}/infra/cloudformation.yml" \
  --stack-name "${STACK_NAME}" \
  --region "${AWS_REGION}" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    Environment="${ENVIRONMENT}" \
    ApiImageUri="${API_ECR_REPO}:${IMAGE_TAG}" \
    WorkerImageUri="${WORKER_ECR_REPO}:${IMAGE_TAG}" \
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
