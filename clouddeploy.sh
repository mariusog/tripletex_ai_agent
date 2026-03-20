#!/usr/bin/env bash
# Build and deploy the Tripletex AI Agent to Google Cloud Run.
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Artifact Registry repository created
#   - ANTHROPIC_API_KEY set (or stored in Secret Manager)
#
# Usage:
#   ./clouddeploy.sh [PROJECT_ID] [REGION]

set -euo pipefail

PROJECT_ID="${1:-${GCP_PROJECT_ID:?Set GCP_PROJECT_ID or pass as first argument}}"
REGION="${2:-europe-north1}"
SERVICE_NAME="tripletex-agent"
REPO_NAME="tripletex"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO_NAME/$SERVICE_NAME"

echo "=== Building and pushing container image ==="
gcloud builds submit \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --tag "$IMAGE:latest" \
    --timeout=600

echo "=== Deploying to Cloud Run ==="
gcloud run deploy "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --image "$IMAGE:latest" \
    --platform managed \
    --allow-unauthenticated \
    --port 8080 \
    --timeout 300 \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 10 \
    --concurrency 1 \
    --set-env-vars "PORT=8080" \
    --set-secrets "ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest"

echo "=== Deployment complete ==="
gcloud run services describe "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format "value(status.url)"
