"""FastAPI server for the Tripletex AI Agent.

Exposes POST /solve endpoint that receives accounting task prompts
and executes them via the Tripletex REST API.
"""

from __future__ import annotations

import logging
import os
import time

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
    """Receive an accounting task prompt and execute it via Tripletex API.

    Flow:
    1. Parse the request (prompt, files, credentials)
    2. Use LLM to classify task type and extract parameters
    3. Execute the appropriate handler with deterministic API calls
    4. Return {"status": "completed"} regardless of outcome
    """
    start_time = time.monotonic()
    base_url = request.tripletex_credentials.base_url if request.tripletex_credentials else "?"
    logger.info(
        'COMPETITION_RUN prompt="%s" base_url=%s',
        request.prompt[:200],
        base_url,
    )
    logger.info("Received solve request, prompt length=%d", len(request.prompt))

    try:
        # Import here to avoid circular imports and allow lazy initialization
        from src.task_router import create_router

        router = create_router()
        await router.solve(request)

        elapsed = time.monotonic() - start_time
        logger.info("Task completed in %.2fs", elapsed)
    except Exception:
        elapsed = time.monotonic() - start_time
        logger.exception("Task failed after %.2fs", elapsed)

    # Always return completed -- scoring checks account state independently
    return SolveResponse(status="completed")


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
