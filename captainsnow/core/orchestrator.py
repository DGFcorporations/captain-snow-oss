import importlib
import time
from collections import deque
from typing import Dict
from core.model_router import ModelRouter
from core.memory import Memory
from core.agent_loop import run_agent_loop
from core.tools import build_tool_schemas
from skills.base import Skill


# All skills available to the orchestrator — name → module.ClassName
_SKILL_REGISTRY = {
    "seo_core":           ("skills.seo_core",           "SeoCoreSkill"),
    "browser":            ("skills.browser",             "BrowserSkill"),
    "fileops":            ("skills.fileops",             "FileopsSkill"),
    "stripe":             ("skills.stripe",              "StripeSkill"),
    "content":            ("skills.content",             "ContentSkill"),
    "watchers":           ("skills.watchers",            "WatchersSkill"),
    "email_ops":          ("skills.email_ops",           "EmailOpsSkill"),
    "airtable":           ("skills.airtable",            "AirtableSkill"),
    "search":             ("skills.search",              "SearchSkill"),
    "megaplan":           ("skills.megaplan",            "MegaplanSkill"),
    "planner":            ("skills.megaplan",            "MegaplanSkill"),  # legacy name → megaplan
    "revenue_consultant": ("skills.revenue_consultant",  "RevenueConsultantSkill"),
    "supabase_connector": ("skills.supabase_connector",  "SupabaseConnectorSkill"),
    "google_workspace":   ("skills.google_workspace",    "GoogleWorkspaceSkill"),
    "route_optimizer":    ("skills.route_optimizer",     "RouteOptimizerSkill"),
    "agent_overseer":     ("skills.agent_overseer",      "AgentOverseerSkill"),
    "github_ops":         ("skills.github_ops",          "GithubOpsSkill"),
    "file_gen":           ("skills.file_gen",            "FileGenSkill"),
}


class CaptainOrchestrator:
    def __init__(self, config: dict):
        self.config = config
        self.router = ModelRouter(config)
        self.memory = Memory(config, router=self.router)
        self.skills: Dict[str, Skill] = {}
        self._morning_done = False
        self._recent_turns: deque = deque(maxlen=6)
        self._max_steps = int(config.get("agent", {}).get("max_steps", 24))
        # Audit ring buffer — every skill invocation lands here. The
        # guardrail/telemetry hook: who called what, when, and whether it
        # succeeded. In-memory only; nothing persisted or exported.
        self.call_log: deque = deque(maxlen=200)
        self._load_skills()
        self.tools = build_tool_schemas(self.skills)

    def _short_term_context(self) -> str:
        if not self._recent_turns:
            return ""
        lines = ["[RECENT CONVERSATION — this session, most recent last]"]
        for u, a in self._recent_turns:
            lines.append(f"User: {u}")
            lines.append(f"Captain Snow: {a[:400]}")
        lines.append("[/RECENT CONVERSATION]")
        return "\n".join(lines)

    def _load_skills(self):
        enabled = self.config.get("skills", {}).get("enabled", [])
        # Force add the new skills if not explicitly disabled
        if "github_ops" not in enabled: enabled.append("github_ops")
        if "file_gen" not in enabled: enabled.append("file_gen")
        if "megaplan" not in enabled and "planner" not in enabled:
            enabled.append("megaplan")

        for skill_name in enabled:
            if skill_name not in _SKILL_REGISTRY:
                print(f"Warning: unknown skill '{skill_name}' — not in registry.")
                continue
            mod_path, cls_name = _SKILL_REGISTRY[skill_name]
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)
                instance = cls(self.config, self.router, self.memory)
                instance._orchestrator = self
                self.skills[skill_name] = instance
            except Exception as e:
                print(f"Warning: Could not load skill '{skill_name}': {e}")

    def _build_system_prompt(self) -> str:
        persona = self.config.get("persona", {})
        user_name = self.config.get("user", {}).get("name", "Captain")
        return (
            f"You are {persona.get('name', 'CaptainSnow')}, "
            f"{persona.get('role', 'a helpful AI assistant')} for {user_name}. "
            f"Personality: {persona.get('personality', 'Helpful and direct.')} "
            f"Tone: {persona.get('tone', 'Professional but approachable.')} "
            f"Style: {persona.get('style', 'Keep responses concise.')} "
            f"Address the user as {persona.get('owner', 'Captain')}.\n\n"
            "You are an AUTONOMOUS AGENT. Break down complex requests and solve them "
            "step-by-step using the provided tools. After each tool result, analyze it: "
            "if the goal is met, reply in plain text with the final answer; otherwise "
            "call the next tool. For multi-step goals prefer the 'megaplan' tool, which "
            "produces a contract, executes phases with verification, and re-plans on failure.\n\n"
            "If the user's message is a short confirmation (\"yes\", \"do it\", \"go ahead\", "
            "\"sounds good\") responding to something YOU suggested earlier in "
            "[RECENT CONVERSATION], you MUST call the tool that carries out that suggestion."
        )

    async def process_request(self, user_input: str) -> str:
        lazy_mode = self.config.get("agent", {}).get("lazy_mode", True)

        if not self._morning_done:
            self._morning_done = True
            if not lazy_mode:
                recap = await self.memory.morning_recap()
                context = recap + "\n" + self.memory.recall_relevant_context(user_input)
            else:
                context = self.memory.recall_relevant_context(user_input)
        else:
            context = self.memory.recall_relevant_context(user_input)

        recent = self._short_term_context()
        enriched_input = f"{recent}\n[PAST CONTEXT]\n{context}\n[/PAST CONTEXT]\n{user_input}"

        messages = [{"role": "user", "content": enriched_input}]
        res = await run_agent_loop(
            self.router,
            self.invoke_skill,
            self._build_system_prompt(),
            messages,
            tools=self.tools,
            max_steps=self._max_steps,
        )
        await self.memory.log_interaction(user_input, res)
        self._recent_turns.append((user_input, res))
        return res

    async def invoke_skill(self, skill_name: str, task: dict) -> str:
        """Single chokepoint for all skill execution. The agent loop and the
        megaplan skill both route through here so guardrails (the call log,
        future rate limits/cooldowns) cannot be bypassed via a second path."""
        started = time.monotonic()
        if skill_name not in self.skills:
            result = f"Skill '{skill_name}' is not enabled or does not exist."
        else:
            try:
                result = await self.skills[skill_name].execute(task)
            except Exception as e:
                result = f"Error executing skill {skill_name}: {e}"
        self.call_log.append({
            "ts": time.time(),
            "skill": skill_name,
            "ok": not result.startswith("Error"),
            "elapsed_s": round(time.monotonic() - started, 3),
            "result_len": len(result),
        })
        return result
