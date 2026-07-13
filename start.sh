#!/bin/sh
# Captain Snow container entrypoint.
# Starts llama-server once (model stays loaded in RAM — no per-request reload),
# then runs the web UI + Telegram bot. If llama-server dies, the router's
# cascade falls through to cloud providers, so the agent keeps working.

MODEL_PATH="${LLAMA_MODEL_PATH:-/app/models/Qwen3-1.7B-Q4_K_M.gguf}"

if [ -f "$MODEL_PATH" ] && command -v llama-server >/dev/null 2>&1; then
    # --reasoning-budget 0 disables Qwen3 <think> blocks — critical for the
    # 16-token intent-classification calls. Bound to loopback only.
    llama-server \
        -m "$MODEL_PATH" \
        --host 127.0.0.1 \
        --port 8081 \
        --ctx-size 4096 \
        --threads "$(nproc)" \
        --reasoning-budget 0 \
        --log-disable &
    echo "llama-server starting on 127.0.0.1:8081 with $MODEL_PATH"
else
    echo "Local model or llama-server missing — running cloud-only."
fi

exec captainsnow serve
