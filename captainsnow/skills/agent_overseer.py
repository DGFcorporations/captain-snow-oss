import httpx
from .base import Skill

class AgentOverseerSkill(Skill):
    async def execute(self, task: dict) -> str:
        endpoints = self.config.get("integrations", {}).get("agents", {})
        if not endpoints:
            return "No agents configured under integrations.agents."
        status = {}
        for name, url in endpoints.items():
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{url}/health", timeout=5)
                    status[name] = "OK" if resp.status_code == 200 else f"DOWN ({resp.status_code})"
            except Exception:
                status[name] = "UNREACHABLE"
        return "\n".join(f"{k}: {v}" for k, v in status.items())