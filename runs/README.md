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
| Original | `tripletex-agent` | `python scripts/capture_runs.py --service tripletex-agent` |

### Capture from ALL services at once
```bash
for svc in tripletex-agent tripletex-agent-2 tripletex-agent-magnus tripletex-agent-stian; do
  python scripts/capture_runs.py --service "$svc" --limit 500
done
```

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

## How to use this data

### Find problems
- **High API call counts** — compare against optimal in `src/constants.py`
- **4xx errors** — reduce efficiency bonus, check `errors` and `error_details`
- **Misclassifications** — wrong `task_type` for the prompt language
- **`<UNKNOWN>` params** — LLM failed to extract a field
- **Missing task types** — task types we've never seen

### Track coverage
```bash
# See which task types we've encountered
ls runs/ | sed 's/.*_\(.*\)_tripletex.*/\1/' | sort | uniq -c | sort -rn
```

### Compare against optimal
Check `src/constants.py` `OPTIMAL_CALL_COUNTS` — every call above optimal costs us efficiency bonus points.

## Important notes

- **GETs count!** The proxy counts ALL requests (GET, POST, PUT, DELETE) toward the efficiency score
- **Zero errors = max bonus.** Any 4xx error reduces the efficiency multiplier
- **Each submission = fresh sandbox.** Entities don't carry over between runs
- **Best score kept forever.** Bad runs never lower your score
- **Prompts come in 7 languages**: NO, EN, ES, PT, NN, DE, FR

## Requirements for capture

Your service needs the `COMPETITION_RUN` log line in `src/server.py`. If you're running the latest code from `Magnus-attempt` branch, this is already included.
