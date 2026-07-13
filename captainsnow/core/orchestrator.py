import asyncio
import importlib
from collections import deque
from typing import Dict
from core.model_router import ModelRouter
from core.memory import Memory
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
    "planner":            ("skills.planner",             "PlannerSkill"),
    "revenue_consultant": ("skills.revenue_consultant",  "RevenueConsultantSkill"),
    "supabase_connector": ("skills.supabase_connector",  "SupabaseConnectorSkill"),
    "google_workspace":   ("skills.google_workspace",    "GoogleWorkspaceSkill"),
    "route_optimizer":    ("skills.route_optimizer",     "RouteOptimizerSkill"),
    "agent_overseer":     ("skills.agent_overseer",      "AgentOverseerSkill"),
}

# Intent word → skill name
_INTENT_SKILL_MAP = {
    "seo":      "seo_core",
    "stripe":   "stripe",
    "browser":  "browser",
    "login":    "browser",
    "content":  "content",
    "file":     "fileops",
    "monitor":  "watchers",
    "email":    "email_ops",
    "airtable": "airtable",
    "search":   "search",
    "plan":     "planner",
    "revenue":  "revenue_consultant",
    "database": "supabase_connector",
    "route":    "route_optimizer",
    "google":   "google_workspace",
}

_VALID_INTENTS = set(_INTENT_SKILL_MAP.keys()) | {"general"}


class CaptainOrchestrator:
    def __init__(self, config: dict):
        self.config = config
        self.router = ModelRouter(config)
        self.memory = Memory(config, router=self.router)
        self.skills: Dict[str, Skill] = {}
        self._morning_done = False
        # In-process short-term memory — the persisted memory bank only
        # consolidates once a day, so without this a follow-up like "yes,
        # do it" has no way to know what "it" refers to. Bounded so it can't
        # grow unbounded on a long-running container.
        self._recent_turns: deque = deque(maxlen=6)
        self._load_skills()

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
        for skill_name in self.config["skills"]["enabled"]:
            if skill_name not in _SKILL_REGISTRY:
                print(f"Warning: unknown skill '{skill_name}' — not in registry.")
                continue
            mod_path, cls_name = _SKILL_REGISTRY[skill_name]
            try:
                mod = importlib.import_module(mod_path)
                cls = getattr(mod, cls_name)
                self.skills[skill_name] = cls(self.config, self.router, self.memory)
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
            f"Address the user as {persona.get('owner', 'Captain')}."
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

        # Classify with recent turns folded in — a bare "yes, do it" or "go
        # ahead" only carries a real intent once the prior suggestion is
        # visible to the classifier.
        classify_input = f"{recent}\n{user_input}" if recent else user_input
        intent = await self.router.classify_intent(classify_input)

        skill_name = _INTENT_SKILL_MAP.get(intent)
        if skill_name and skill_name in self.skills:
            # Give the skill the same recent-turn context so a follow-up
            # confirmation still carries whatever specifics (a URL, a name)
            # were mentioned in the earlier suggestion. Current message first
            # — word-scanning extractors (URL/domain heuristics) take the
            # first match, so the current turn must win over stale context.
            skill_prompt = f"{user_input}\n{recent}" if recent else user_input
            task_payload = {"prompt": skill_prompt, "action": intent}
            # Special routing for browser login
            if intent == "login":
                task_payload["action"] = "login"
            try:
                result = await self.skills[skill_name].execute(task_payload)
            except Exception as e:
                result = f"Skill error ({skill_name}): {e}"
            plain = await self._report_results(user_input, [result])
            await self.memory.log_interaction(user_input, plain)
            self._recent_turns.append((user_input, plain))
            return plain
        else:
            res = await self._general_chat(enriched_input)
            await self.memory.log_interaction(user_input, res)
            self._recent_turns.append((user_input, res))
            return res

    def _parse_action(self, text: str):
        """Parse [ACTION: skill_name, prompt: "instruction"] blocks robustly."""
        if "[ACTION:" not in text:
            return None
        try:
            start_idx = text.find("[ACTION:")
            end_idx = text.find("]", start_idx)
            if end_idx == -1:
                return None
            action_content = text[start_idx + 8 : end_idx].strip()
            
            parts = action_content.split(",", 1)
            skill_name = parts[0].strip()
            
            prompt_part = parts[1].strip()
            if prompt_part.startswith("prompt:"):
                action_prompt = prompt_part[7:].strip()
                if (action_prompt.startswith('"') and action_prompt.endswith('"')) or \
                   (action_prompt.startswith("'") and action_prompt.endswith("'")):
                    action_prompt = action_prompt[1:-1].strip()
                return skill_name, action_prompt
        except Exception:
            pass
        return None

    async def _general_chat(self, user_input: str) -> str:
        # Build description of available tools
        skill_descriptions = []
        for name, skill in self.skills.items():
            desc = skill.__doc__ or f"Execute tasks related to {name}."
            desc = " ".join(desc.split())
            skill_descriptions.append(f"- {name}: {desc}")
        skills_text = "\n".join(skill_descriptions)

        base_system = self._build_system_prompt()
        system = (
            f"{base_system}\n\n"
            "You have access to the following tools/skills:\n"
            f"{skills_text}\n\n"
            "To run a task or use a skill, output exactly:\n"
            "[ACTION: <skill_name>, prompt: \"<your instruction>\"]\n"
            "Only call one tool at a time. Do not write anything else when you output an [ACTION: ...] block.\n"
            "If you do not need to run a tool to answer the user's question, reply directly in plain text.\n"
            "Once a tool executes and feeds back the [RESULT: ...], you must analyze it, and either call another tool or formulate a final response.\n\n"
            "If the user's message is a short confirmation (\"yes\", \"do it\", \"go ahead\", \"please\", "
            "\"sounds good\") responding to something YOU suggested earlier in [RECENT CONVERSATION], you "
            "MUST output the [ACTION: ...] block for that specific suggestion — reusing the exact URL, name, "
            "or detail already mentioned. Do NOT describe the task again or offer more options; that is what "
            "the user is complaining about when they say you never actually do anything."
        )

        history = [{"role": "user", "content": user_input}]

        for _ in range(5):
            # Format history for query
            formatted_msg = ""
            for msg in history:
                role = "User" if msg["role"] == "user" else "Assistant"
                formatted_msg += f"{role}: {msg['content']}\n"

            try:
                response = await self.router.query(system, formatted_msg, complexity="high")
            except Exception as e:
                return f"Model error: {e}"

            response = response.strip()
            action = self._parse_action(response)
            if not action:
                # Direct answer
                return response

            skill_name, action_prompt = action
            if skill_name in self.skills:
                try:
                    result = await self.skills[skill_name].execute({"prompt": action_prompt, "action": "execute"})
                except Exception as e:
                    result = f"Error executing skill {skill_name}: {e}"
            else:
                result = f"Skill '{skill_name}' is not enabled or does not exist."

            history.append({"role": "assistant", "content": response})
            history.append({"role": "user", "content": f"[RESULT: {skill_name}]\n{result}\n[/RESULT]"})

        # If we exceeded the limit, return the last assistant response
        final_responses = [h["content"] for h in history if h["role"] == "assistant"]
        return final_responses[-1] if final_responses else "Task took too many steps to complete."

    async def _report_results(self, user_input: str, results: list) -> str:
        lines = []
        for result in results:
            if isinstance(result, dict):
                action = result.get("action", "something")
                status = result.get("status", "done")
                details = result.get("details", "")
                emoji = "✅" if status == "success" else "⚠️"
                lines.append(f"{emoji} {action}: {details}")
            else:
                lines.append(str(result))
        return "\n".join(lines)
