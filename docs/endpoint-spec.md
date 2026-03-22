# Endpoint Specification

## Requirements

- **Method:** POST
- **Path:** `/solve`
- **Content-Type:** `application/json`
- **Protocol:** HTTPS only (not HTTP)
- **Timeout:** 300 seconds (5 minutes)
- **Success response:** `{"status": "completed"}` with HTTP 200

## Request Format

```json
{
  "prompt": "Natural language task description (in one of 7 languages)",
  "files": [
    {
      "filename": "receipt.pdf",
      "content_base64": "base64-encoded-data",
      "mime_type": "application/pdf"
    }
  ],
  "tripletex_credentials": {
    "base_url": "https://proxy-url/v2",
    "session_token": "abc123"
  }
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes | Task description in one of 7 languages |
| `files` | array | No | Attached files (PDFs, images) as base64 |
| `files[].filename` | string | Yes | Original filename |
| `files[].content_base64` | string | Yes | Base64-encoded file content |
| `files[].mime_type` | string | Yes | MIME type (e.g., `application/pdf`, `image/png`) |
| `tripletex_credentials.base_url` | string | Yes | Proxy API endpoint (use this, NOT the standard Tripletex URL) |
| `tripletex_credentials.session_token` | string | Yes | Authentication token |

## Tripletex API Authentication

All API calls to the provided `base_url` use **Basic Auth**:
- **Username:** `0` (the character zero)
- **Password:** the `session_token` from the request

```python
import requests
response = requests.get(
    f"{base_url}/employee",
    auth=("0", session_token),
    params={"fields": "id,firstName,lastName,email"}
)
```

## Optional API Key Protection

If configured, competition platform sends `Authorization: Bearer <your-api-key>` header with requests to your endpoint. Use this to prevent unauthorized access.

## Response

Always return:
```json
{"status": "completed"}
```
with HTTP 200, regardless of whether the task was fully solved. The scoring system checks the Tripletex account state independently.
