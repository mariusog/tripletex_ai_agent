# Sandbox Environment

## Getting Your Sandbox

1. Navigate to the Tripletex submission page on `app.ainm.no`
2. Click "Get Sandbox Account"
3. Receive:
   - **Tripletex UI URL:** `https://kkpqfuj-amager.tripletex.dev`
   - **API base URL:** `https://kkpqfuj-amager.tripletex.dev/v2`
   - **Session token** for API authentication

## Web UI Access

- Enter your sandbox email at the Tripletex URL
- First login: click "Forgot password" to create Visma Connect credentials
- Credentials persist and are reusable across test accounts

## API Testing

```python
import requests

BASE_URL = "https://kkpqfuj-amager.tripletex.dev/v2"
SESSION_TOKEN = "your-token"

response = requests.get(
    f"{BASE_URL}/employee",
    auth=("0", SESSION_TOKEN),
    params={"fields": "id,firstName,lastName,email"}
)
print(response.json())
```

```bash
curl -u "0:your-session-token-here" \
  "https://kkpqfuj-amager.tripletex.dev/v2/employee?fields=id,firstName,lastName"
```

## Sandbox vs Competition

| Aspect | Sandbox | Competition |
|--------|---------|-------------|
| Account | Persistent, team-owned | Fresh per submission |
| API access | Direct to Tripletex | Via authenticated proxy |
| Data | Accumulates over time | Starts empty each run |
| Scoring | None | Automated field-by-field |

## Important Details

- **Token expiration:** March 31, 2026
- **Shared:** All team members share one sandbox
- **Field selection:** Use `?fields=*` to see all available fields
- **Pagination:** Use `?from=0&count=100`
- **Response format:** List endpoints return `{"fullResultSize": N, "values": [...]}`
- **UTF-8:** Norwegian characters (ae, oe, aa) work properly when sent as UTF-8
