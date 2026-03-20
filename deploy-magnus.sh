#!/usr/bin/env bash
# Deploy Magnus's isolated instance of the Tripletex AI Agent.
#
# Uses Application Default Credentials (no browser needed).
# Deploys to a SEPARATE Cloud Run service so it doesn't conflict with teammates.
#
# Usage:
#   ./deploy-magnus.sh

set -euo pipefail

PROJECT_ID="ai-nm26osl-1792"
REGION="europe-west1"
SERVICE_NAME="tripletex-agent-magnus"

echo "=== Refreshing access token from ADC ==="
python3 -c "
import google.auth, google.auth.transport.requests
creds, _ = google.auth.default()
creds.refresh(google.auth.transport.requests.Request())
with open('/tmp/gcloud_token', 'w') as f:
    f.write(creds.token)
print('Token refreshed, expires:', creds.expiry)
" 2>/dev/null

gcloud config set auth/access_token_file /tmp/gcloud_token 2>/dev/null
gcloud config set project "$PROJECT_ID" 2>/dev/null

echo "=== Deploying $SERVICE_NAME to Cloud Run ==="
echo "This is Magnus's isolated deployment — won't affect teammates."
echo ""

gcloud run deploy "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --source /workspaces/tripletex_ai_agent \
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
echo "=== Deployment complete ==="
URL=$(gcloud run services describe "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --format "value(status.url)")
echo "Service URL: $URL"
echo ""
echo "Submit this to the competition: ${URL}/solve"
echo ""
echo "To check logs:"
echo "  gcloud run services logs read $SERVICE_NAME --project $PROJECT_ID --region $REGION --limit 50"
