# Competition Runs — Shared Knowledge Hub

Every competition task we encounter is captured here so the whole team can learn from each run. **Please contribute your runs!**

## Quick Start (30 seconds)

```bash
# 1. Capture runs from your service
python scripts/capture_runs.py --service YOUR-SERVICE-NAME

# 2. Review what was captured
python scripts/summarize_runs.py

# 3. Share with the team
git add runs/
git commit -m "Add runs from [your-name]"
git push
```

### Service names per teammate
| Person | Service | Command |
|--------|---------|---------|
| Magnus | `tripletex-agent-magnus` | `python scripts/capture_runs.py` (default) |
| Team shared | `tripletex-agent-2` | `python scripts/capture_runs.py --service tripletex-agent-2` |
| Stian | `tripletex-agent-stian` | `python scripts/capture_runs.py --service tripletex-agent-stian` |

**Add your service name here when you set one up!**

## Auto-posting to GCS

`tripletex-agent-2` automatically saves run data to GCS after each competition submission:
```
gs://ai-nm26osl-1792-nmiai/tripletex-runs/
```

Check runs: `gsutil ls gs://ai-nm26osl-1792-nmiai/tripletex-runs/`

## Enable run capture on your service

Add this to your `src/server.py` in the `solve` function, right after `logger.info("Received solve request...")`:

```python
is_competition = "tx-proxy" in (request.tripletex_credentials.base_url or "")
if is_competition:
    import json
    logger.info(
        "COMPETITION_RUN prompt=%s base_url=%s",
        json.dumps(request.prompt[:500]),
        request.tripletex_credentials.base_url,
    )
```

Without this, the capture script still works but gets less data.

## What gets captured

Each competition submission is saved as a JSON file: `YYYY-MM-DD_HH-MM-SS_{task_type}_{service}.json`

```json
{
  "timestamp": "2026-03-20 21:22:49",
  "prompt": "The original prompt (in any of 7 languages)",
  "task_type": "register_payment",
  "params": {"customer": "Nordlicht GmbH", "amount": 26400},
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

## Important notes

- **GETs are FREE!** Only POST, PUT, DELETE, PATCH count toward efficiency scoring
- **4xx errors reduce the efficiency bonus.** Avoid trial-and-error
- **Zero errors + minimal writes = max bonus.** Can up to double your tier score
- **Each submission = fresh sandbox.** Entities don't carry over between runs
- **Best score kept forever.** Bad runs never lower your score
- **Prompts come in 7 languages**: NO, EN, ES, PT, NN, DE, FR
- **30 task types × 56 variants** (7 languages × 8 data sets)

## Requirements for capture

Your service needs the `COMPETITION_RUN` log line in `src/server.py`. If you're running the latest code from `Marius-attempt` branch, this is already included.
