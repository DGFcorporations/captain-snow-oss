import httpx
from .base import Skill


class ContentSkill(Skill):
    """Draft blog posts and marketing copy; can save drafts to WordPress."""

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "Create a blog post about solo business growth.")

        system = (
            "You are a professional copywriter. Generate an engaging, SEO-optimized "
            "blog post with a Title and Body. Format in Markdown, title as a # heading."
        )
        content = await self.router.query(system, prompt, complexity="medium")

        wp = self.config.get("integrations", {}).get("wordpress", {})
        wp_ready = all(
            wp.get(k) and ph not in wp.get(k, "")
            for k, ph in (("url", "WORDPRESS_URL"), ("username", "WORDPRESS_USERNAME"),
                          ("app_password", "WP_APP_PASSWORD"))
        )

        if not wp_ready:
            return f"Generated content (no publishing configured — draft below):\n\n{content}"

        # Explicit "publish" in the request goes live; everything else lands as
        # a WordPress draft so nothing appears publicly without a human look.
        status = "publish" if "publish" in prompt.lower() else "draft"
        try:
            link = await self._post_to_wordpress(wp, content, status)
            verb = "Published" if status == "publish" else "Saved as WordPress draft"
            return f"{verb}: {link}\n\nPreview:\n{content[:500]}..."
        except Exception as e:
            return (
                f"Content generated, but WordPress upload failed ({e}). Draft below:\n\n{content}"
            )

    async def _post_to_wordpress(self, wp: dict, content_md: str, status: str) -> str:
        lines = content_md.strip().splitlines()
        title = lines[0].lstrip("# ").strip() if lines else "Untitled"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else content_md
        endpoint = wp["url"].rstrip("/") + "/wp-json/wp/v2/posts"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                endpoint,
                auth=(wp["username"], wp["app_password"]),
                json={"title": title, "content": body, "status": status},
            )
            resp.raise_for_status()
            return resp.json().get("link", endpoint)
