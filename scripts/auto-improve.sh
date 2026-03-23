#!/usr/bin/env bash
set -euo pipefail
cd .
echo "=== $(date '+%H:%M:%S') Auto-improve cycle ==="
python3 -c "
import google.auth, google.auth.transport.requests
creds, _ = google.auth.default()
creds.refresh(google.auth.transport.requests.Request())
with open('/tmp/gcloud_token', 'w') as f: f.write(creds.token)
" 2>/dev/null
gcloud config set auth/access_token_file /tmp/gcloud_token 2>/dev/null
echo "--- Capturing runs ---"
for svc in tripletex-agent tripletex-agent-2; do
  python scripts/capture_runs.py --service "$svc" --limit 2000 2>&1 | grep "Saved" || true
done
echo "--- Analyzing ---"
python scripts/summarize_runs.py 2>&1 | tail -15
echo "=== Cycle complete ==="
