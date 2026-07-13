# Captain Snow — slim default image.
#
# Cloud-first: routes to free-tier providers (OpenRouter/Qwen/Groq/Gemini) —
# no compiled binaries, no multi-GB model file, nothing baked in beyond
# Python and your API keys. This is what makes Captain Snow runnable on a
# $5 VPS, a Raspberry Pi, or a phone (Termux) instead of needing a beefy box.
#
# Want offline/zero-API-cost local inference instead? Use Dockerfile.local —
# it adds a compiled llama.cpp server + a ~1GB model (~1.5-2GB extra RAM when
# active). Most people don't need it: the free cloud tiers configured here
# are already fast and cost nothing.
#
# The browser/login skill needs Chromium, which is NOT installed by this
# image (it's a 600MB+ download). Run `playwright install --with-deps
# chromium` in your own derived image, or accept that `browser`/`login`
# requests will fail with a clear "browser not installed" error.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CAPTAINSNOW_CONFIG=/app/config.yaml

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-bake chroma's ONNX embedding model (~80MB) so the first message after
# boot doesn't stall on a runtime download.
RUN python -c "from chromadb.utils.embedding_functions import DefaultEmbeddingFunction; DefaultEmbeddingFunction()(['warmup'])"

COPY setup.py ./
COPY captainsnow ./captainsnow
RUN pip install -e . --no-deps

COPY config.example.yaml ./config.yaml
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 8000

VOLUME ["/app/captainsnow_memory"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["./start.sh"]
