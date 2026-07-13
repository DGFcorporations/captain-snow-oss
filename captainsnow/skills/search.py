import httpx
import json
from .base import Skill


class SearchSkill(Skill):
    """Web search — DuckDuckGo free tier, Serper as optional upgrade."""

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        query = task.get("query") or await self._extract_query(prompt)
        n = task.get("n", 5)

        serper_key = (
            self.config.get("integrations", {})
            .get("search", {})
            .get("serper_api_key", "")
        )
        use_serper = bool(serper_key) and "SERPER" not in serper_key

        if use_serper:
            return await self._serper_search(query, serper_key, n)
        return await self._ddg_search(query, n)

    async def _extract_query(self, prompt: str) -> str:
        system = "Extract only the search query from this request. Return the query text only, no extra words."
        return (await self.router.query(system, prompt, max_tokens=64)).strip()

    async def _ddg_search(self, query: str, n: int) -> str:
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=n):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", "")[:200],
                    })
            return self._format_results(query, results)
        except ImportError:
            return "duckduckgo-search is not installed. Run: pip install duckduckgo-search"
        except Exception as e:
            return f"Search failed: {e}"

    async def _serper_search(self, query: str, api_key: str, n: int) -> str:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": n},
                    timeout=10,
                )
                data = resp.json()
                results = []
                for item in data.get("organic", [])[:n]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", "")[:200],
                    })
                return self._format_results(query, results)
        except Exception as e:
            return f"Serper search failed: {e}"

    @staticmethod
    def _format_results(query: str, results: list) -> str:
        if not results:
            return f"No results found for '{query}'."
        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**\n   {r['url']}\n   {r['snippet']}\n")
        return "\n".join(lines)
