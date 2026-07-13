"""
LLM Router — local-first, free-first cascade.

Provider priority (cost-optimised for 24/7 operation):
  1. Local GGUF  — qwen2.5-1.5b baked into the image (zero cost, zero API calls)
  2. Ollama      — local dev only (skipped in prod when host is blank)
  3. OpenRouter  — free-tier model
  4. Qwen        — DashScope free quota
  5. Groq        — free tier (rate-limits often)
  6. Gemini      — free tier then cheap
  7. DeepSeek    — paid but near-free (~$0.07/M tokens)
  8. Kimi        — Moonshot paid (last resort)

No startup probes — providers are only contacted when actually needed.
Failed providers fall through to the next automatically.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)

# Providers tried in this order; unconfigured providers are silently skipped.
# Production runs in Docker with a baked-in GGUF model, so `local` is first.
# `ollama` stays available for local dev on a machine that already runs Ollama.
_PROVIDER_ORDER = ["local", "ollama", "openrouter", "qwen", "groq", "gemini", "deepseek", "kimi"]

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
        "default_model": "gemini-2.0-flash",
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
        self.local_model = None
        self.ollama_client = None
        self.groq_client = None
        # One cached client per OpenAI-compat provider
        self._compat_clients: dict[str, Any] = {}

    # ── Configuration helpers ─────────────────────────────────────────────

    def _is_configured(self, name: str) -> bool:
        """Return True only if the provider has a real (non-placeholder) API key or host."""
        cfg = self.config.get("models", {}).get(name, {})
        if name == "ollama":
            return bool(cfg.get("host", ""))
        api_key = cfg.get("api_key", "")
        if not api_key:
            return False
        return not any(ph in api_key for ph in _PLACEHOLDERS)

    def _has_local(self) -> bool:
        # Local inference = llama-server running as a sidecar (started by
        # start.sh). If it's down, the query raises and the cascade falls
        # through to cloud providers — connection-refused on loopback is
        # instant, so a dead server costs nothing.
        return bool(self.config.get("models", {}).get("local", {}).get("server_url", ""))

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

        # MUST stay in sync with _INTENT_SKILL_MAP in core/orchestrator.py.
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
            # prompt, near-instant) — the 1.7B local model misroutes too often to
            # be trusted with classification. Local remains the offline fallback.
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
        """Send a prompt through the provider cascade.

        Args:
            max_tokens: Hard cap on response length. Pass 16 for classify-style calls.
            use_vision:  If True, route directly to Gemini (only provider with vision here).
        """
        if use_vision:
            if self._is_configured("gemini"):
                return await self._call_gemini_vision(system_prompt, user_message)
            raise RuntimeError("Vision requested but Gemini is not configured.")

        temperature = 0.2
        keep_alive = self.config.get("agent", {}).get("ollama_keep_alive", "5m")
        last_exc: Optional[Exception] = None

        preferred = self.config.get("user", {}).get("preferred_ai_model")
        providers = list(_PROVIDER_ORDER)

        # Upgrade route for complex reasoning tasks if cloud is configured
        cloud_providers = ["groq", "gemini", "deepseek", "openrouter", "qwen", "kimi"]
        has_configured_cloud = any(self._is_configured(p) for p in cloud_providers)

        if (complexity in ("medium", "high")) and has_configured_cloud:
            configured_cloud = [p for p in cloud_providers if self._is_configured(p)]
            if preferred in configured_cloud:
                configured_cloud.remove(preferred)
                configured_cloud.insert(0, preferred)
            providers = configured_cloud + [p for p in providers if p not in configured_cloud]
        elif preferred and preferred in providers:
            if preferred in ["local", "ollama"] or self._is_configured(preferred):
                providers.remove(preferred)
                providers.insert(0, preferred)

        for provider in providers:
            try:
                if provider == "ollama":
                    if not self._is_configured("ollama"):
                        continue
                    return await self._call_ollama(system_prompt, user_message, max_tokens, temperature, keep_alive)

                elif provider == "groq":
                    if not self._is_configured("groq"):
                        continue
                    return await self._call_groq(system_prompt, user_message, max_tokens, temperature)

                elif provider == "local":
                    if not self._has_local():
                        continue
                    return await self._call_local(system_prompt, user_message, max_tokens, temperature)

                elif provider in _OPENAI_COMPAT:
                    if not self._is_configured(provider):
                        continue
                    return await self._call_compat(provider, system_prompt, user_message, max_tokens, temperature)

            except Exception as exc:
                log.warning("ModelRouter: %s failed (%s), trying next provider.", provider, type(exc).__name__)
                last_exc = exc
                continue

        raise last_exc or RuntimeError("ModelRouter: all providers exhausted.")

    # ── Provider implementations ──────────────────────────────────────────

    async def _call_ollama(
        self, system: str, user: str, max_tokens: int, temperature: float, keep_alive: str = "5m"
    ) -> str:
        import openai
        if not self.ollama_client:
            ollama_cfg = self.config["models"].get("ollama", {})
            host = ollama_cfg.get("host", "http://localhost:11434/v1")
            self.ollama_client = openai.AsyncOpenAI(api_key="ollama", base_url=host)
        ollama_cfg = self.config["models"].get("ollama", {})
        model = ollama_cfg.get("model", "qwen2.5:0.5b")
        response = await self.ollama_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"keep_alive": keep_alive},
        )
        return response.choices[0].message.content

    async def _call_groq(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        from groq import AsyncGroq
        if not self.groq_client:
            api_key = self.config["models"]["groq"]["api_key"]
            self.groq_client = AsyncGroq(api_key=api_key)
        completion = await self.groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=self.config["models"]["groq"]["model"],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return completion.choices[0].message.content

    async def _call_compat(
        self, provider: str, system: str, user: str, max_tokens: int, temperature: float
    ) -> str:
        """Handle all OpenAI-compatible cloud providers (openrouter, qwen, deepseek, gemini, kimi)."""
        import openai
        if provider not in self._compat_clients:
            cfg = self.config["models"].get(provider, {})
            prov_def = _OPENAI_COMPAT[provider]
            self._compat_clients[provider] = openai.AsyncOpenAI(
                api_key=cfg.get("api_key"),
                base_url=prov_def["base_url"],
                default_headers=prov_def.get("extra_headers", {}),
            )
        client = self._compat_clients[provider]
        cfg = self.config["models"].get(provider, {})
        prov_def = _OPENAI_COMPAT[provider]
        model = cfg.get("model", prov_def["default_model"])
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    async def _call_gemini_vision(self, system: str, user: str, image_data: bytes = None) -> str:
        import openai, base64
        if "gemini" not in self._compat_clients:
            cfg = self.config["models"].get("gemini", {})
            prov_def = _OPENAI_COMPAT["gemini"]
            self._compat_clients["gemini"] = openai.AsyncOpenAI(
                api_key=cfg.get("api_key"),
                base_url=prov_def["base_url"],
            )
        client = self._compat_clients["gemini"]
        cfg = self.config["models"].get("gemini", {})
        model = cfg.get("model", "gemini-2.0-flash")
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
        return response.choices[0].message.content

    async def _call_local(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        # llama-server sidecar (see start.sh) — OpenAI-compatible, model stays
        # loaded in RAM so calls cost seconds, not a 1GB reload per message.
        import openai
        local_cfg = self.config.get("models", {}).get("local", {})
        server_url = local_cfg.get("server_url", "http://127.0.0.1:8081/v1")
        if "local" not in self._compat_clients:
            self._compat_clients["local"] = openai.AsyncOpenAI(
                api_key="local",
                base_url=server_url,
                timeout=120.0,
            )
        client = self._compat_clients["local"]
        response = await client.chat.completions.create(
            model=local_cfg.get("model", "local"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._strip_think(response.choices[0].message.content or "")

    @staticmethod
    def _strip_think(text: str) -> str:
        """Remove Qwen3 <think>...</think> reasoning blocks. llama-server is
        launched with --reasoning-budget 0, but this is the safety net — a
        leaked think block breaks 16-token intent classification entirely."""
        import re
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # Unclosed opening tag (response truncated by max_tokens)
        if "<think>" in text:
            text = text.split("<think>", 1)[0]
        # --reasoning-budget 0 suppresses the opening <think> tag but still
        # emits the closing one — strip a bare leading </think> plus any
        # blank line after it (observed live: leaks into every field a
        # skill builds from a raw router.query() call, e.g. keyword lists).
        text = text.strip()
        if text.startswith("</think>"):
            text = text[len("</think>"):].lstrip("\n").strip()
        return text
