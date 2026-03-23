#!/usr/bin/env bash
# Safe deploy: validates code before deploying to tripletex-agent-2
set -euo pipefail

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="europe-west1"
SERVICE_NAME="tripletex-agent-2"

echo "=== Pre-deploy validation ==="

# 1. Check all handlers import cleanly
HANDLER_COUNT=$(python3 -c "from src.handlers import HANDLER_REGISTRY; print(len(HANDLER_REGISTRY))" 2>&1)
if [ "$HANDLER_COUNT" -lt 41 ]; then
    echo "ABORT: Only $HANDLER_COUNT handlers registered (expected 41+)"
    exit 1
fi
echo "✓ $HANDLER_COUNT handlers registered"

# 2. Lint
ruff check src/ 2>&1 || { echo "ABORT: Lint failed"; exit 1; }
echo "✓ Lint passed"

# 3. Tests
python -m pytest tests/ -q --tb=line -m "not slow" 2>&1 | tail -3
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "ABORT: Tests failed"
    exit 1
fi
echo "✓ Tests passed"

echo ""
echo "=== Deploying $SERVICE_NAME ==="

# Refresh token
python3 -c "
import google.auth, google.auth.transport.requests
creds, _ = google.auth.default()
creds.refresh(google.auth.transport.requests.Request())
with open('/tmp/gcloud_token', 'w') as f:
    f.write(creds.token)
" 2>/dev/null

gcloud run deploy "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --source . \
    --allow-unauthenticated \
    --port 8080 \
    --timeout 300 \
    --memory 1Gi \
    --cpu 2 \
    --min-instances 1 \
    --max-instances 10 \
    --concurrency 1 \
    --set-env-vars "ANTHROPIC_VERTEX_PROJECT_ID=$PROJECT_ID,CLOUD_ML_REGION=us-east5"

echo ""
echo "=== Deploy complete ==="
URL=$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --format "value(status.url)")
echo "Service URL: $URL/solve"
