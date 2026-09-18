"""Provider health checks — backs `captainsnow doctor` and scripts/provider_health.py.

Catches free-tier slug rot: providers silently rename/deprecate model slugs,
and ModelRouter quietly falls through to the next provider when one fails —
so a dead slug degrades CS for weeks before anyone notices.

Checks each configured provider:
  1. API key present and non-placeholder (after ${ENV} expansion)
  2. Model slug configured
  3. (ping=True) live ~10-token chat completion + latency
"""

from __future__ import annotations

import asyncio
import time

from .model_router import _PROVIDER_ORDER, _OPENAI_COMPAT, _PLACEHOLDERS, ModelRouter

PING_PROMPT = "Reply with exactly: OK"
TIMEOUT_S = 20


def _key_status(api_key: str) -> str:
    if not api_key:
        return "missing"
    if any(ph in api_key for ph in _PLACEHOLDERS):
        return "placeholder"
    return "set"


def check_config(config: dict) -> list[dict]:
    """Static checks — no network. Returns one row per provider in cascade order."""
    rows = []
    models_cfg = config.get("models", {})
    for name in _PROVIDER_ORDER:
        cfg = models_cfg.get(name, {})
        prov_def = _OPENAI_COMPAT.get(name, {})
        api_key = cfg.get("api_key", "")
        key = _key_status(api_key)
        model = cfg.get("model") or prov_def.get("default_model", "")
        rows.append({
            "provider": name,
            "key": key,
            "model": model,
            "configured": key == "set",
            "status": "skipped" if key != "set" else "unknown",
            "latency_ms": None,
            "error": None,
        })
    return rows


async def _ping_provider(router: ModelRouter, name: str) -> tuple[str, int, str | None]:
    """One tiny chat call against a single provider, bypassing the cascade."""
    start = time.monotonic()
    messages = [{"role": "user", "content": PING_PROMPT}]
    try:
        if name == "groq":
            await asyncio.wait_for(router._call_groq(messages, 8, 0.0), TIMEOUT_S)
        else:
            await asyncio.wait_for(router._call_compat(name, messages, 8, 0.0), TIMEOUT_S)
        return "live", int((time.monotonic() - start) * 1000), None
    except asyncio.TimeoutError:
        return "dead", int((time.monotonic() - start) * 1000), f"timeout>{TIMEOUT_S}s"
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        return "dead", int((time.monotonic() - start) * 1000), msg[:160]


async def ping_all(config: dict, rows: list[dict]) -> list[dict]:
    router = ModelRouter(config)
    for row in rows:
        if not row["configured"]:
            continue
        status, latency, error = await _ping_provider(router, row["provider"])
        row.update(status=status, latency_ms=latency, error=error)
    return rows


def render_table(rows: list[dict], pinged: bool) -> str:
    lines = [
        f"{'provider':<12} {'key':<11} {'model':<46} {'status':<8} {'ms':>7}  error",
        "-" * 100,
    ]
    for r in rows:
        status = r["status"]
        if status == "unknown":
            status = "no-ping" if not pinged else status
        lat = "" if r["latency_ms"] is None else str(r["latency_ms"])
        err = r["error"] or ""
        lines.append(f"{r['provider']:<12} {r['key']:<11} {r['model']:<46} {status:<8} {lat:>7}  {err}")

    dead = [r["provider"] for r in rows if r["status"] == "dead"]
    live = [r["provider"] for r in rows if r["status"] == "live"]
    skipped = [r["provider"] for r in rows if r["status"] == "skipped"]
    lines.append("-" * 100)
    lines.append(f"live={len(live)} dead={len(dead)} skipped(unconfigured)={len(skipped)}")
    if dead:
        lines.append("DEAD: " + ", ".join(dead) + " — update the model slug or key in config.yaml")
    if not pinged:
        lines.append("(config check only — pass --ping for live calls)")
    return "\n".join(lines)


def exit_code(rows: list[dict], pinged: bool) -> int:
    """1 if any configured provider is confirmed dead, or no provider is usable."""
    dead = [r for r in rows if r["status"] == "dead"]
    usable = [r for r in rows if r["status"] in ("live", "no-ping", "unknown") and r["configured"]]
    if dead or (pinged and not usable):
        return 1
    if not pinged and not any(r["configured"] for r in rows):
        return 1
    return 0
