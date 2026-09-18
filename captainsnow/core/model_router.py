"""
LLM Router — free-first cloud cascade.

Provider priority (cost-optimised for 24/7 operation):
  1. OpenRouter  — free-tier model
  2. Qwen        — DashScope free quota
  3. Groq        — free tier (rate-limits often)
  4. Gemini      — free tier then cheap
  5. DeepSeek    — paid but near-free (~$0.07/M tokens)
  6. Kimi        — Moonshot paid (last resort)

No local inference: the baked-in 1.7B GGUF was removed (unreliable tool
calling — see docs/benchmarks-2026-09.md). Every remaining provider speaks
OpenAI-compatible chat.completions *with* native `tools`/`tool_calls`, so
the agent loop needs no fallback action protocol.

Free-tier model slugs rot — providers rename and deprecate them. A dead slug
fails silently into the next provider, so run `captainsnow doctor`
(scripts/provider_health.py) weekly; quarterly review in the benchmarks doc.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

log = logging.getLogger(__name__)

# Providers tried in this order; unconfigured providers are silently skipped.
_PROVIDER_ORDER = ["openrouter", "qwen", "groq", "gemini", "deepseek", "kimi"]

# OpenAI-compatible cloud providers — base_url + model config key
_OPENAI_COMPAT = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "extra_headers": {
            "HTTP-Referer": "https://captainsnow.local",
            "X-Title": "CaptainSnow",
        },
    },
    "qwen": {
        # International DashScope endpoint — keys issued outside mainland
        # China (the common case) are region-locked and get a bare
        # "invalid_api_key" 401 against the mainland endpoint even when
        # correct. If your key IS a mainland key, point this back at
        # https://dashscope.aliyuncs.com/compatible-mode/v1.
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.5-flash",
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
}

# Placeholder strings that mean "key not actually set"
_PLACEHOLDERS = ("_KEY", "_HERE", "OPTIONAL")


class ModelRouter:
    def __init__(self, config: dict):
        self.config = config
        self.groq_client = None
        # One cached client per OpenAI-compat provider
        self._compat_clients: dict[str, Any] = {}

    # ── Configuration helpers ─────────────────────────────────────────────

    def _is_configured(self, name: str) -> bool:
        """Return True only if the provider has a real (non-placeholder) API key."""
        cfg = self.config.get("models", {}).get(name, {})
        api_key = cfg.get("api_key", "")
        if not api_key:
            return False
        return not any(ph in api_key for ph in _PLACEHOLDERS)

    # ── Public API ────────────────────────────────────────────────────────

    # Unambiguous product/service names → intent. Deterministic fast-path:
    # no LLM call, no chance of a small model misrouting "check stripe" to
    # the browser skill. Only names that can't mean anything else belong here.
    _KEYWORD_INTENTS = {
        "stripe": "stripe",
        "airtable": "airtable",
        "supabase": "database",
        "seo": "seo",
    }

    async def classify_intent(self, text: str) -> str:
        """Classify a user message into one of the routing categories.
        Uses max_tokens=16 — response is always a single word."""
        import re
        lowered = text.lower()
        matched = {
            intent
            for kw, intent in self._KEYWORD_INTENTS.items()
            if re.search(rf"\b{kw}\b", lowered)
        }
        if len(matched) == 1:
            return matched.pop()

        # Valid categories. NOTE: classify_intent currently has no callers —
        # the orchestrator routes everything through the agent loop. Kept for
        # future intent-routing use.
        _valid = {
            "seo", "stripe", "browser", "login", "content", "file",
            "monitor", "email", "airtable", "search", "plan", "revenue",
            "database", "route", "google", "general",
        }
        prompt = (
            "Classify the request into exactly one category. Output one word only, no punctuation.\n"
            "Categories:\n"
            "  seo       — SEO audits, keyword research, rankings\n"
            "  stripe    — payments, customers, charges, balances\n"
            "  browser   — open a website, scrape, fill a form\n"
            "  login     — log into a saved site\n"
            "  content   — draft blog posts, social, marketing copy\n"
            "  file      — read/write/move local files\n"
            "  monitor   — uptime checks, alerts, watchers\n"
            "  email     — send or read email (Zoho)\n"
            "  airtable  — Airtable records\n"
            "  search    — web search / look something up online\n"
            "  plan      — multi-step planning / break a goal into steps\n"
            "  revenue   — revenue, MRR, financial consulting\n"
            "  database  — Supabase / SQL queries\n"
            "  route     — driving routes, optimization, Google Maps\n"
            "  google    — Google Sheets / Docs / Drive / Workspace\n"
            "  general   — chat, greetings, anything else\n"
            f"Request: {text}\nCategory:"
        )
        try:
            # complexity="medium" prefers configured cloud (free tiers, ~200-token
            # prompt, near-instant).
            raw = await self.query(
                "You are a concise intent classifier.", prompt,
                complexity="medium", max_tokens=16,
            )
            # Strip markdown/punctuation; search for a valid category keyword in the tokens
            cleaned = "".join(c if c.isalnum() else " " for c in (raw or "").lower())
            tokens = cleaned.strip().split()
            for token in tokens:
                if token in _valid:
                    return token
            return "general"
        except Exception:
            return "general"

    async def query(
        self,
        system_prompt: str,
        user_message: str,
        complexity: str = "simple",
        use_vision: bool = False,
        max_tokens: int = 1024,
    ) -> str:
        """Send a prompt through the provider cascade. Returns text content.

        Args:
            max_tokens: Hard cap on response length. Pass 16 for classify-style calls.
            use_vision:  If True, route directly to Gemini (only provider with vision here).
        """
        if use_vision:
            if self._is_configured("gemini"):
                return await self._call_gemini_vision(system_prompt, user_message)
            raise RuntimeError("Vision requested but Gemini is not configured.")

        msg = await self._request(
            system_prompt,
            [{"role": "user", "content": user_message}],
            complexity=complexity,
            max_tokens=max_tokens,
        )
        return getattr(msg, "content", None) or ""

    async def chat(
        self,
        system_prompt: str,
        messages: List[dict],
        tools: Optional[List[dict]] = None,
        complexity: str = "high",
        max_tokens: int = 4096,
    ) -> dict:
        """Multi-turn chat with optional tool calling. Returns a plain dict:
        {"content": str, "tool_calls": [{"id", "type", "function": {...}}]}.

        The full OpenAI-format `messages` list is passed through, so the
        caller owns conversation state (trajectory) — the router stays
        stateless apart from cached HTTP clients.
        """
        msg = await self._request(
            system_prompt, messages,
            complexity=complexity, max_tokens=max_tokens, tools=tools,
        )
        return {
            "content": getattr(msg, "content", None) or "",
            "tool_calls": _dump_tool_calls(getattr(msg, "tool_calls", None)),
        }

    # ── Cascade ───────────────────────────────────────────────────────────

    def _provider_sequence(self, complexity: str) -> list:
        preferred = self.config.get("user", {}).get("preferred_ai_model")
        providers = list(_PROVIDER_ORDER)

        # Upgrade route for complex reasoning tasks: prefer cloud providers
        # (all of them now — local is gone).
        cloud_providers = ["groq", "gemini", "deepseek", "openrouter", "qwen", "kimi"]
        has_configured_cloud = any(self._is_configured(p) for p in cloud_providers)

        if (complexity in ("medium", "high")) and has_configured_cloud:
            configured_cloud = [p for p in cloud_providers if self._is_configured(p)]
            if preferred in configured_cloud:
                configured_cloud.remove(preferred)
                configured_cloud.insert(0, preferred)
            providers = configured_cloud + [p for p in providers if p not in configured_cloud]
        elif preferred and preferred in providers:
            if self._is_configured(preferred):
                providers.remove(preferred)
                providers.insert(0, preferred)

        return providers

    async def _request(
        self,
        system: str,
        messages: List[dict],
        complexity: str,
        max_tokens: int,
        tools: Optional[List[dict]] = None,
    ):
        """Walk the cascade and return the provider's raw `message` object
        (content + tool_calls). Raises the last provider error if all fail."""
        temperature = 0.2
        full_messages = [{"role": "system", "content": system}] + list(messages)
        last_exc: Optional[Exception] = None

        for provider in self._provider_sequence(complexity):
            try:
                if provider == "groq":
                    if not self._is_configured("groq"):
                        continue
                    return await self._call_groq(full_messages, max_tokens, temperature, tools)
                elif provider in _OPENAI_COMPAT:
                    if not self._is_configured(provider):
                        continue
                    return await self._call_compat(provider, full_messages, max_tokens, temperature, tools)
            except Exception as exc:
                log.warning("ModelRouter: %s failed (%s), trying next provider.", provider, type(exc).__name__)
                last_exc = exc
                continue

        raise last_exc or RuntimeError("ModelRouter: all providers exhausted.")

    # ── Provider implementations ──────────────────────────────────────────

    async def _call_groq(self, messages, max_tokens, temperature, tools=None):
        from groq import AsyncGroq
        if not self.groq_client:
            api_key = self.config["models"]["groq"]["api_key"]
            self.groq_client = AsyncGroq(api_key=api_key)
        kwargs = dict(
            messages=messages,
            model=self.config["models"]["groq"]["model"],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        completion = await self.groq_client.chat.completions.create(**kwargs)
        return completion.choices[0].message

    async def _call_compat(self, provider, messages, max_tokens, temperature, tools=None):
        """Handle all OpenAI-compatible cloud providers (openrouter, qwen, deepseek, gemini, kimi)."""
        import openai
        if provider not in self._compat_clients:
            cfg = self.config.get("models", {}).get(provider, {})
            prov_def = _OPENAI_COMPAT[provider]
            self._compat_clients[provider] = openai.AsyncOpenAI(
                api_key=cfg.get("api_key"),
                base_url=prov_def["base_url"],
                default_headers=prov_def.get("extra_headers", {}),
            )
        client = self._compat_clients[provider]
        cfg = self.config.get("models", {}).get(provider, {})
        prov_def = _OPENAI_COMPAT[provider]
        model = cfg.get("model", prov_def["default_model"])
        kwargs = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message

    async def _call_gemini_vision(self, system: str, user: str, image_data: bytes = None) -> str:
        import openai, base64
        if "gemini" not in self._compat_clients:
            cfg = self.config.get("models", {}).get("gemini", {})
            prov_def = _OPENAI_COMPAT["gemini"]
            self._compat_clients["gemini"] = openai.AsyncOpenAI(
                api_key=cfg.get("api_key"),
                base_url=prov_def["base_url"],
            )
        client = self._compat_clients["gemini"]
        cfg = self.config.get("models", {}).get("gemini", {})
        model = cfg.get("model", "gemini-2.5-flash")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if image_data:
            b64 = base64.b64encode(image_data).decode()
            messages[1]["content"] = [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=512,
        )
        return response.choices[0].message.content or ""


def _dump_tool_calls(tool_calls) -> list:
    """Normalize SDK tool_call objects into plain dicts for the agent loop
    and for re-sending inside assistant messages on the next turn."""
    out = []
    for tc in tool_calls or []:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            out.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", "") or "",
                },
            })
        else:
            fn = getattr(tc, "function", None)
            out.append({
                "id": getattr(tc, "id", "") or "",
                "type": "function",
                "function": {
                    "name": getattr(fn, "name", "") or "",
                    "arguments": getattr(fn, "arguments", "") or "",
                },
            })
    return out
