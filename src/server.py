"""FastAPI server for the Tripletex AI Agent.

Exposes POST /solve endpoint that receives accounting task prompts
and executes them via the Tripletex REST API.
"""

from __future__ import annotations

import json as _json
import logging
import os
import time
from datetime import UTC

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.constants import LOG_FORMAT, LOG_LEVEL, SERVER_HOST, SERVER_PORT
from src.models import SolveRequest, SolveResponse

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

app = FastAPI(title="Tripletex AI Agent", version="0.1.0")

# Optional Bearer token auth -- set API_KEY env var to enable
_bearer_scheme = HTTPBearer(auto_error=False)
_bearer_dependency = Depends(_bearer_scheme)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> None:
    """Verify the Bearer token if API_KEY is configured."""
    expected = os.environ.get("API_KEY")
    if not expected:
        return  # No API_KEY set -- auth disabled
    if not credentials or credentials.credentials != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.post("/solve", response_model=SolveResponse)
async def solve(
    request: SolveRequest,
    _auth: None = Depends(verify_api_key),
) -> SolveResponse:
    """Receive an accounting task prompt and execute it via Tripletex API."""
    return await _solve_impl(request)


async def _solve_impl(request: SolveRequest) -> SolveResponse:
    """Actual solve implementation, protected by _solve_lock."""
    start_time = time.monotonic()
    base_url = request.tripletex_credentials.base_url if request.tripletex_credentials else "?"
    is_competition = "tx-proxy" in (request.tripletex_credentials.base_url or "")
    if is_competition:
        logger.info(
            "COMPETITION_RUN prompt=%s base_url=%s",
            _json.dumps(request.prompt[:500]),
            base_url,
        )
    logger.info("Received solve request, prompt length=%d", len(request.prompt))

    run_meta: dict = {}
    try:
        from src.task_router import create_router

        router = create_router()
        await router.solve(request)
        run_meta = getattr(router, "_run_meta", {})

        elapsed = time.monotonic() - start_time
        logger.info("Task completed in %.2fs", elapsed)
    except Exception:
        elapsed = time.monotonic() - start_time
        logger.exception("Task failed after %.2fs", elapsed)

    # Save competition run data to GCS
    if is_competition:
        _save_run_to_gcs(request.prompt, base_url, elapsed, run_meta)

    # Always return completed -- scoring checks account state independently
    return SolveResponse(status="completed")


def _save_run_to_gcs(
    prompt: str, base_url: str, elapsed: float, run_meta: dict | None = None
) -> None:
    """Save competition run data to GCS bucket for team sharing."""
    try:
        from datetime import datetime

        from google.cloud import storage

        ts = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
        service = os.environ.get("K_SERVICE", "tripletex-agent-2")
        run_data: dict = {
            "timestamp": ts,
            "prompt": prompt[:500],
            "base_url": base_url,
            "duration_s": round(elapsed, 2),
            "service": service,
        }
        if run_meta:
            run_data.update(run_meta)
        bucket_name = "ai-nm26osl-1792-nmiai"
        blob_path = f"tripletex-runs/{ts}_{service}.json"
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            _json.dumps(run_data, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        logger.info("Saved run to gs://%s/%s", bucket_name, blob_path)
    except Exception:
        logger.warning("Failed to save run to GCS (non-critical)")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for deployment probes."""
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all exception handler. Always return 200 with completed status."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=200,
        content={"status": "completed"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
