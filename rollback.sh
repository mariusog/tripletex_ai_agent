#!/usr/bin/env bash
# Quick rollback to previous Cloud Run revision
set -euo pipefail

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="europe-west1"
SERVICE_NAME="tripletex-agent-2"

echo "=== Current revisions ==="
gcloud run revisions list --service "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --limit 3 --format "table(name,status.conditions.status,spec.containerConcurrency)"

echo ""
PREV=$(gcloud run revisions list --service "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" --limit 2 --format "value(name)" | tail -1)
echo "Rolling back to: $PREV"

gcloud run services update-traffic "$SERVICE_NAME" \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --to-revisions="$PREV=100"

echo "✓ Rolled back to $PREV"
