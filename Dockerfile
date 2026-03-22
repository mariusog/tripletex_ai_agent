# Stage 1: Install dependencies (cached layer)
FROM python:3.12-slim AS deps

WORKDIR /app

# Copy only dependency metadata first for layer caching
COPY pyproject.toml ./

# Install production dependencies only (no dev extras)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Stage 2: Final image with application code
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application source
COPY src/ ./src/
COPY pyproject.toml ./

# Install the project itself (no dependencies, already installed)
RUN pip install --no-cache-dir --no-deps .

# Cloud Run sets PORT env var; default to 8080
ENV PORT=8080

EXPOSE 8080

# Run with uvicorn -- single worker for Cloud Run (scales via instances)
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "310"]
