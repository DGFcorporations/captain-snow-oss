"""
Multi-step task planner — borrowed from AgenticSeek's planner_agent pattern.

When a request needs more than one skill (e.g., "search for contractors, email me the results"),
the planner decomposes it into a JSON task list, executes each step in order, and passes
the output of each step as context into the next.
"""

import json
import importlib
from .base import Skill


# Skills that the planner can delegate to, mapped to their class name
_SKILL_MAP = {
    "search": "SearchSkill",
    "email": "EmailOpsSkill",
    "browser": "BrowserSkill",
    "seo": "SeoCoreSkill",
    "stripe": "StripeSkill",
    "airtable": "AirtableSkill",
    "content": "ContentSkill",
    "fileops": "FileopsSkill",
}

_MODULE_MAP = {
    "search": "skills.search",
    "email": "skills.email_ops",
    "browser": "skills.browser",
    "seo": "skills.seo_core",
    "stripe": "skills.stripe",
    "airtable": "skills.airtable",
    "content": "skills.content",
    "fileops": "skills.fileops",
}


class PlannerSkill(Skill):
    """Breaks a complex multi-step request into a plan and executes it step by step."""

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        plan = await self._build_plan(prompt)
        if not plan:
            return "Could not build a plan for this request. Please be more specific."
        return await self._execute_plan(plan, prompt)

    async def _build_plan(self, goal: str) -> list:
        available = ", ".join(_SKILL_MAP.keys())
        system = (
            f"You are a task planner. Break this goal into ordered steps using only these skills: {available}. "
            "Return a JSON array only, no other text. Each item: "
            "{\"step\": 1, \"skill\": \"search\", \"task\": \"what to do\"}. "
            "Maximum 5 steps. If one step suffices, return a single-item array."
        )
        try:
            # Plan JSON must parse — route to cloud; the local 1.7B emits
            # malformed JSON often enough to break the whole planner.
            raw = await self.router.query(system, goal, complexity="high", max_tokens=512)
            raw = raw.strip()
            # Strip markdown fences if present
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()
            plan = json.loads(raw)
            if isinstance(plan, list):
                return plan
        except Exception:
            pass
        return []

    async def _execute_plan(self, plan: list, original_goal: str) -> str:
        step_results = []
        context = ""

        for step_def in plan:
            step_num = step_def.get("step", "?")
            skill_name = step_def.get("skill", "").lower()
            step_task = step_def.get("task", "")

            # Enrich step task with context from previous steps
            if context:
                enriched_task = f"{step_task}\n\nContext from previous steps:\n{context}"
            else:
                enriched_task = step_task

            skill_inst = self._load_skill(skill_name)
            if skill_inst is None:
                result = f"[Step {step_num}] Skill '{skill_name}' not available — skipped."
            else:
                try:
                    result = await skill_inst.execute({"prompt": enriched_task, "action": ""})
                    result = f"[Step {step_num} — {skill_name}]\n{result}"
                except Exception as e:
                    result = f"[Step {step_num} — {skill_name}] Error: {e}"

            step_results.append(result)
            # Feed result into next step's context (truncated to avoid overflow)
            context += result[:600] + "\n"

        # Final summary
        summary_prompt = (
            f"Original goal: {original_goal}\n\n"
            "Step results:\n" + "\n\n".join(step_results) +
            "\n\nProvide a concise final summary of what was accomplished."
        )
        try:
            summary = await self.router.query(
                "You are a results summarizer. Be brief and direct.", summary_prompt, max_tokens=256
            )
        except Exception:
            summary = "Plan complete."

        full = "\n\n".join(step_results) + f"\n\n**Summary:** {summary}"
        return full

    def _load_skill(self, skill_name: str):
        if skill_name not in _MODULE_MAP:
            return None
        try:
            mod = importlib.import_module(_MODULE_MAP[skill_name])
            cls = getattr(mod, _SKILL_MAP[skill_name])
            return cls(self.config, self.router, self.memory)
        except Exception:
            return None
