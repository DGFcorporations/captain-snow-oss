"""
Browser skill — Playwright headless browser with authenticated login support.

Login flow borrows AgenticSeek's form-filling heuristics:
detect username/password fields by name/id/label, fill them, click submit.
Passwords referenced as ENV:VARNAME are resolved from environment variables.
"""

import os
import asyncio
from .base import Skill


class BrowserSkill(Skill):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._playwright = None
        self._browser = None

    async def _get_browser(self):
        """Lazy-init a persistent Chromium instance."""
        if self._browser is None or not self._browser.is_connected():
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        return self._browser

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # ── Public execute router ─────────────────────────────────────────────

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        action = task.get("action", "browse")
        lower = prompt.lower()

        if action == "login" or any(w in lower for w in ["log in", "login", "sign in", "signin"]):
            return await self._handle_login(prompt)
        elif action == "fill_form" or "fill" in lower:
            return await self._handle_fill(prompt)
        else:
            url = self._extract_url(prompt)
            if not url:
                return "Please specify a URL to browse."
            return await self._browse(url)

    # ── Basic browse ─────────────────────────────────────────────────────

    async def _browse(self, url: str) -> str:
        try:
            browser = await self._get_browser()
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            content = await page.content()
            title = await page.title()
            await page.close()
            return f"Browsed to {url} - Title: {title}\nFirst 500 chars: {content[:500]}"
        except Exception as e:
            return f"Browser error: {e}"

    # ── Authenticated login ───────────────────────────────────────────────

    async def _handle_login(self, prompt: str) -> str:
        """Parse login details from prompt then attempt login."""
        system = (
            "Extract login details from this request. "
            "Return JSON: {\"url\": \"...\", \"username\": \"...\", \"password\": \"...\"}. "
            "If password looks like ENV:VARNAME, keep it as-is."
        )
        import json
        try:
            raw = await self.router.query(system, prompt, max_tokens=128)
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            data = json.loads(raw)
            url = data.get("url", "")
            username = data.get("username", "")
            password = self._resolve_password(data.get("password", ""))
            if not url or not username or not password:
                return "Could not extract login details. Provide: URL, username, and password."
            return await self.login(url, username, password)
        except Exception as e:
            return f"Login parsing error: {e}"

    async def login(self, url: str, username: str, password: str) -> str:
        """
        Navigate to url, detect username/password fields by common name/id/label
        heuristics, fill them, click submit, and report the outcome.
        """
        password = self._resolve_password(password)
        try:
            browser = await self._get_browser()
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)

            # ── Find username field ───────────────────────────────────────
            user_selectors = [
                'input[name="username"]', 'input[name="email"]',
                'input[name="user"]', 'input[name="login"]',
                'input[id*="user" i]', 'input[id*="email" i]',
                'input[type="email"]', 'input[autocomplete="username"]',
                'input[autocomplete="email"]',
            ]
            user_field = await self._find_first(page, user_selectors)

            # ── Find password field ───────────────────────────────────────
            pass_selectors = [
                'input[type="password"]',
                'input[name="password"]', 'input[name="pass"]',
                'input[id*="pass" i]', 'input[autocomplete="current-password"]',
            ]
            pass_field = await self._find_first(page, pass_selectors)

            if not user_field or not pass_field:
                text = await page.content()
                await page.close()
                return f"Could not find login fields at {url}. Page may use a custom form or JS-rendered inputs."

            await user_field.fill(username)
            await asyncio.sleep(0.3)
            await pass_field.fill(password)
            await asyncio.sleep(0.3)

            # ── Click submit ──────────────────────────────────────────────
            submit_selectors = [
                'button[type="submit"]', 'input[type="submit"]',
                'button:has-text("Log in")', 'button:has-text("Login")',
                'button:has-text("Sign in")', 'button:has-text("Continue")',
            ]
            submit = await self._find_first(page, submit_selectors)
            if submit:
                await submit.click()
            else:
                await pass_field.press("Enter")

            # ── Wait for navigation and verify ───────────────────────────
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass

            final_url = page.url
            title = await page.title()
            await page.close()

            # Simple heuristic: if we're still on the same login URL, it may have failed
            if "login" in final_url.lower() or "signin" in final_url.lower():
                return f"Login may have failed — still on login page. Title: {title}"
            return f"Login successful. Now at: {final_url} — {title}"

        except Exception as e:
            return f"Login error: {e}"

    async def fill_and_submit(self, url: str, fields: dict) -> str:
        """General-purpose form filler. fields = {selector_or_name: value}."""
        try:
            browser = await self._get_browser()
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            for selector, value in fields.items():
                try:
                    el = await page.query_selector(selector) or await page.query_selector(f'[name="{selector}"]')
                    if el:
                        await el.fill(str(value))
                except Exception:
                    pass
            submit = await self._find_first(page, ['button[type="submit"]', 'input[type="submit"]'])
            if submit:
                await submit.click()
            await page.wait_for_load_state("domcontentloaded", timeout=6000)
            title = await page.title()
            final_url = page.url
            await page.close()
            return f"Form submitted. Now at: {final_url} — {title}"
        except Exception as e:
            return f"Form fill error: {e}"

    async def _handle_fill(self, prompt: str) -> str:
        system = (
            "Extract URL and form fields from this request. "
            'Return JSON: {"url": "...", "fields": {"field_name": "value"}}.'
        )
        import json
        try:
            raw = await self.router.query(system, prompt, max_tokens=256)
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            data = json.loads(raw)
            return await self.fill_and_submit(data["url"], data.get("fields", {}))
        except Exception as e:
            return f"Form fill error: {e}"

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    async def _find_first(page, selectors: list):
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue
        return None

    @staticmethod
    def _resolve_password(password: str) -> str:
        """Resolve ENV:VARNAME references to actual environment variable values."""
        if password and password.upper().startswith("ENV:"):
            var_name = password[4:].strip()
            return os.environ.get(var_name, password)
        return password

    @staticmethod
    def _extract_url(text: str) -> str:
        for word in text.split():
            cleaned = word.strip(".,;:!?\"'()")
            if cleaned.startswith(("http://", "https://")):
                return cleaned
            if "." in cleaned and not cleaned.startswith(".") and not cleaned.endswith("."):
                parts = cleaned.split(".")
                if len(parts) >= 2 and not all(p.isdigit() for p in parts):
                    return "https://" + cleaned
        return ""

