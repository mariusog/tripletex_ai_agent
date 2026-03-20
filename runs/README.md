# Competition Runs

Shared repository of all competition task encounters across teammates.

## How to capture runs

```bash
# Capture from your service (default: tripletex-agent-magnus)
python scripts/capture_runs.py

# Capture from a teammate's service
python scripts/capture_runs.py --service tripletex-agent-2

# Capture more history
python scripts/capture_runs.py --limit 1000
```

## How to share

```bash
git add runs/
git commit -m "Add competition runs from [your-name]"
git push
```

## File format

Each run is saved as `YYYY-MM-DD_HH-MM-SS_{task_type}_{service}.json`:

```json
{
  "timestamp": "2026-03-20 21:22:49",
  "prompt": "The original prompt in any of 7 languages",
  "task_type": "register_payment",
  "params": {"customer": "...", "amount": 26400},
  "api_calls": [
    {"method": "GET", "endpoint": "/customer", "status": 200, "duration_s": 4.4},
    {"method": "POST", "endpoint": "/order", "status": 201, "duration_s": 4.8}
  ],
  "total_api_calls": 9,
  "total_duration_s": 55.79,
  "errors": [],
  "service": "tripletex-agent-magnus"
}
```

## What to look for

- **High API call counts** — compare against optimal in `src/constants.py`
- **4xx errors** — these reduce efficiency bonus
- **Misclassifications** — wrong task_type for the prompt
- **Slow calls** — anything over 5s per call is the proxy being slow
- **Missing task types** — prompts we don't handle
