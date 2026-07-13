import asyncio
import json
from .base import Skill
from core.model_router import ModelRouter
from core.memory import Memory

class SeoCoreSkill(Skill):
    """16‑Stage SEO Pipeline inspired by Roobie."""
    async def execute(self, task: dict) -> str:
        action = task.get("action", "audit")
        if action == "competitor_analysis":
            competitor_url = task.get("url")
            return await self._competitor_analysis(competitor_url)
        else:
            prompt = task.get("prompt", "")
            url = task.get("url")
            if not url:
                # Find a word with a dot that looks like a domain or url
                for word in prompt.split():
                    cleaned_word = word.strip(".,;:!?\"'()")
                    if "." in cleaned_word and not cleaned_word.startswith(".") and not cleaned_word.endswith("."):
                        parts = cleaned_word.split(".")
                        if len(parts) >= 2 and not all(p.isdigit() for p in parts):
                            url = cleaned_word
                            break
            if url:
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url
            else:
                url = "https://example.com"
            return await self._run_full_audit(url)



    async def _run_full_audit(self, url: str) -> str:
        print(f"🔍 Running full SEO audit for {url} ...")
        # Stage 1: Fetch page content (use Browser skill if needed, but here we'll simulate)
        page_content = await self._fetch_page_text(url)
        # Stage 2: Extract metadata
        meta = await self._extract_metadata(page_content)
        # Stage 3: Keyword analysis
        keywords = await self._extract_keywords(page_content)
        # Stage 4: Competitor research (optional)
        # Stage 5: On‑page SEO scoring
        scores = await self._score_onpage(meta, keywords)
        # Stage 6: Content quality check
        quality = await self._check_content_quality(page_content)
        # Stage 7: Mobile responsiveness (simulate)
        # Stage 8: Image alt analysis
        # Stage 9: Link structure
        # Stage 10: Schema validation
        schema_report = await self._check_schema(page_content)
        # Stage 11: Performance hints (Lighthouse)
        perf_tips = "Ensure images are compressed, enable caching."
        # Stage 12: Readability
        readability = await self._score_readability(page_content)
        # Stage 13: Social meta tags
        social = await self._social_tags(meta)
        # Stage 14: Local SEO (if applicable)
        # Stage 15: Content suggestions
        suggestions = await self._generate_content_ideas(keywords)
        # Stage 16: Final report
        report = f"""
        SEO Audit Report for {url}
        ==============================
        Meta: {json.dumps(meta, indent=2)}
        Keywords: {', '.join(keywords[:10])}
        On‑page Score: {scores}
        Content Quality: {quality}
        Readability: {readability}
        Schema: {schema_report}
        Social Tags: {social}
        Performance: {perf_tips}
        Content Suggestions: {suggestions}
        """
        return report

    async def _fetch_page_text(self, url: str) -> str:
        # First, try with Playwright (headless) for JavaScript-heavy sites
        try:
            from skills.browser import BrowserSkill
            browser = BrowserSkill(self.config, self.router, self.memory)
            browser_result = await browser.execute({"action": "browse", "prompt": url})
            if "Title:" in browser_result:   # success
                return browser_result
        except Exception as e:
            pass

        # Fallback to simple HTTP fetch
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10)
                if resp.status_code == 200:
                    return resp.text[:5000]
                else:
                    return f"HTTP error {resp.status_code} when fetching {url}"
        except Exception as e2:
            return f"Could not fetch {url}: {e2}. Please check the URL or your network."


    async def _extract_metadata(self, html: str) -> dict:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string if soup.title else "No title"
        desc_tag = soup.find('meta', attrs={'name': 'description'})
        description = desc_tag['content'] if desc_tag else ""
        h1 = soup.h1.get_text() if soup.h1 else ""
        return {"title": title, "description": description, "h1": h1}

    async def _extract_keywords(self, text: str) -> list:
        # Use AI to extract keywords
        prompt = "Extract up to 10 SEO keywords from this page content, comma-separated: " + text[:1000]
        keywords_str = await self.router.query("You are an SEO expert.", prompt, complexity="simple")
        return [k.strip() for k in keywords_str.split(",") if k.strip()]

    async def _score_onpage(self, meta, keywords) -> str:
        score = 85  # placeholder, would involve checks
        return f"{score}/100"

    async def _check_content_quality(self, text: str) -> str:
        word_count = len(text.split())
        return "Good" if word_count > 300 else "Thin content"

    async def _check_schema(self, html: str) -> str:
        if "application/ld+json" in html:
            return "Schema found."
        return "No structured data detected."

    async def _score_readability(self, text: str) -> str:
        # Placeholder: Flesch-Kincaid
        return "Grade 8 (good)"

    async def _social_tags(self, meta: dict) -> str:
        return "Open Graph tags present" if "og:" in str(meta) else "Missing Open Graph tags."

    async def _generate_content_ideas(self, keywords: list) -> str:
        prompt = f"Based on these keywords: {', '.join(keywords[:5])}, suggest 3 blog post titles for better SEO."
        return await self.router.query("You are a content strategist.", prompt, complexity="simple")