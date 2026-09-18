# Captain Snow — production image for VPS deployment
# Free-first cloud cascade: OpenRouter/Qwen/Groq/Gemini free tiers → paid
# (DeepSeek, Kimi) last. No local inference — the 1.7B GGUF was removed
# (unreliable tool calling; docs/benchmarks-2026-09.md), which also drops the
# llama.cpp compile stage and the ~1.1GB model download from this image.
#
# Layer order matters: everything heavy (deps, Chromium) sits ABOVE the
# source copy, so a code-only push rebuilds in seconds instead of ~15 minutes.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CAPTAINSNOW_CONFIG=/app/config.yaml

# curl for the healthcheck, ca-certificates for TLS to providers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps from requirements.txt only — source is copied much later.
COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Chromium for the Playwright browser skill (~600MB with system libs).
# Without this every browse/login task fails with "Executable doesn't exist".
RUN playwright install --with-deps chromium

# Pre-bake chroma's ONNX embedding model (~80MB) — otherwise the first
# message after every deploy stalls while it downloads at runtime.
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction; DefaultEmbeddingFunction()(['warmup'])"

# ── Source code — everything below here rebuilds on every push ──────────────
COPY setup.py ./
COPY captainsnow ./captainsnow
RUN pip install -e . --no-deps

COPY config.yaml ./config.yaml
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

# FastAPI web UI port — the reverse proxy publishes this
EXPOSE 8000

# Persistent state (memory.db, chroma, transcripts) — mount a host volume here
VOLUME ["/app/captainsnow_memory"]

# Healthcheck for the container runtime.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["./start.sh"]
