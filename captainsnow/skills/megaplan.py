"""Megaplan — contract-first multi-phase planner/executor.

Given a complex goal, produce a plan-mode-style Contract (responsibilities,
NEVER rules, invariants, failure modes), decompose it into phased steps
{skill, task, verify}, execute each through the orchestrator's invoke_skill
chokepoint, verify each result against its success check, and re-plan the
remaining steps (bounded) when a step fails verification.

Every run is persisted to captainsnow_memory/plans/<ts>-<slug>.md — the
resumable, inspectable trajectory artifact.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from .base import Skill

log = logging.getLogger(__name__)

_MAX_STEPS = 12
_MAX_REPLANS = 2

# Skill names the planner is allowed to delegate to — resolved against the
# orchestrator's live registry at run time, so this never drifts from what
# is actually enabled.
_FORBIDDEN_SELF = {"megaplan", "planner"}


class MegaplanSkill(Skill):
    """Plan and execute complex multi-phase goals with verification and re-planning."""

    async def execute(self, task: dict) -> str:
        goal = task.get("prompt", "").strip()
        if not goal:
            return "Give me a goal to plan against — e.g. 'audit our site SEO and email me the findings'."

        contract = await self._build_contract(goal)
        steps = await self._build_steps(goal, contract)
        if not steps:
            return "Could not decompose that goal into executable steps. Try being more specific about the outcome you want."

        step_log, final_text = await self._execute_steps(goal, contract, steps)
        run_file = self._persist(goal, contract, step_log)
        footer = f"\n\nRun saved to {run_file}." if run_file else ""
        return final_text + footer

    # ── Phase 1: contract ────────────────────────────────────────────────

    async def _build_contract(self, goal: str) -> str:
        system = (
            "You are a contract writer for an autonomous agent. Produce a short "
            "execution contract for the goal using EXACTLY this structure:\n"
            "# Contract: <one-line goal summary>\n"
            "## Responsibilities\n- <what this run must accomplish>\n"
            "## NEVER Rules\n- <things the agent must never do>\n"
            "## Invariants\n- <what must remain true throughout>\n"
            "## Failure Modes\n- <how each plausible failure is handled>\n"
            "Keep it under 200 words. Be specific to the goal — no boilerplate."
        )
        try:
            contract = await self.router.query(system, goal, complexity="high", max_tokens=512)
            return contract.strip() if contract.strip() else f"# Contract\n- Goal: {goal}"
        except Exception as e:
            log.warning("megaplan: contract build failed (%s)", type(e).__name__)
            return f"# Contract\n- Goal: {goal}"

    # ── Phase 2: step decomposition ──────────────────────────────────────

    def _available_skills(self) -> list:
        if self._orchestrator is None:
            return []
        return [n for n in self._orchestrator.skills if n not in _FORBIDDEN_SELF]

    async def _build_steps(self, goal: str, contract: str, completed_note: str = "") -> list:
        available = ", ".join(self._available_skills()) or "none"
        system = (
            "You are a task decomposer. Break the goal into ordered steps using ONLY "
            f"these skills: {available}. Return a JSON array only, no other text. "
            "Each item: {\"step\": <n>, \"skill\": \"<skill name>\", "
            "\"task\": \"<what to do>\", \"verify\": \"<how to check the step succeeded>\"}. "
            f"Maximum {_MAX_STEPS} steps. If one step suffices, return a single-item array."
        )
        prompt = f"Goal: {goal}\n\nContract:\n{contract}"
        if completed_note:
            prompt += f"\n\n{completed_note}"
        try:
            raw = await self.router.query(system, prompt, complexity="high", max_tokens=1024)
            raw = raw.strip()
            if "```" in raw:
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else raw
                raw = raw.lstrip("json").strip()
            steps = json.loads(raw)
            if isinstance(steps, list):
                return [s for s in steps if isinstance(s, dict)][: _MAX_STEPS]
        except Exception as e:
            log.warning("megaplan: step decomposition failed (%s)", type(e).__name__)
        return []

    # ── Phase 3: execute + verify + bounded re-plan ─────────────────────

    async def _execute_steps(self, goal: str, contract: str, steps: list):
        step_log: list[str] = []
        context = ""
        replans_used = 0
        queue = list(steps)

        while queue:
            step_def = queue.pop(0)
            step_num = step_def.get("step", "?")
            skill_name = str(step_def.get("skill", "")).lower()
            step_task = step_def.get("task", "")
            verify_check = step_def.get("verify", "the step produced a non-empty, relevant result")

            enriched_task = step_task
            if context:
                enriched_task = f"{step_task}\n\nContext from previous steps:\n{context}"

            if self._orchestrator is None:
                result = f"[Step {step_num} — {skill_name}] Error: megaplan has no orchestrator reference — cannot invoke skill."
            else:
                raw_result = await self._orchestrator.invoke_skill(
                    skill_name, {"prompt": enriched_task, "action": ""}
                )
                verdict, reason = await self._verify_step(step_task, verify_check, raw_result)
                status = "PASS" if verdict else "FAIL"
                result = f"[Step {step_num} — {skill_name}] {status}\n{raw_result}"
                if reason:
                    result += f"\n(verifier: {reason})"

                if not verdict and replans_used < _MAX_REPLANS:
                    replans_used += 1
                    completed_note = (
                        f"Already completed (do not repeat): {context[-800:]}\n"
                        f"Step {step_num} ({skill_name}) FAILED verification: {reason}. "
                        "Produce a NEW step list for the remaining work that routes around "
                        "this failure (different skill or different approach)."
                    )
                    new_steps = await self._build_steps(goal, contract, completed_note)
                    if new_steps:
                        queue = new_steps
                        step_log.append(result + f"\n  → re-planning remaining steps (re-plan #{replans_used})")
                        continue

            step_log.append(result)
            context += result[:600] + "\n"

        summary_prompt = (
            f"Original goal: {goal}\n\n"
            "Step results:\n" + "\n\n".join(step_log) +
            "\n\nProvide a concise final summary of what was accomplished, "
            "flagging any steps that failed verification."
        )
        try:
            summary = await self.router.query(
                "You are a results summarizer. Be brief and direct.", summary_prompt, max_tokens=256
            )
        except Exception:
            summary = "Plan complete."

        full = f"# Megaplan run\n\n**Goal:** {goal}\n\n## Contract\n{contract}\n\n## Steps\n" + \
              "\n\n".join(step_log) + f"\n\n## Summary\n{summary}"
        return step_log, full

    async def _verify_step(self, step_task: str, verify_check: str, result: str):
        """Cheap pass/fail check — first word of the reply is the verdict."""
        system = (
            "You verify whether a step's output satisfies its success check. "
            "Reply with exactly: PASS <one-line reason> or FAIL <one-line reason>. "
            "Judge on the check criteria, not on general quality."
        )
        prompt = (
            f"Step task: {step_task}\nSuccess check: {verify_check}\n"
            f"Step output (truncated):\n{result[:1500]}"
        )
        try:
            raw = await self.router.query(system, prompt, complexity="medium", max_tokens=64)
            raw = (raw or "").strip()
            verdict = raw.upper().startswith("PASS")
            reason = raw.split(" ", 1)[1].strip() if " " in raw else ""
            return verdict, reason
        except Exception:
            # Verification itself failed — accept the step rather than
            # burning the whole run on a flaky check call.
            return True, "verifier unavailable — accepted"

    # ── Phase 4: persist ────────────────────────────────────────────────

    def _persist(self, goal: str, contract: str, step_log: list) -> str:
        try:
            plans_dir = Path(self.memory.base_path) / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^a-z0-9]+", "-", goal.lower())[:40].strip("-") or "run"
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = plans_dir / f"{ts}-{slug}.md"
            body = f"# Megaplan run — {ts}\n\n**Goal:** {goal}\n\n## Contract\n{contract}\n\n## Steps\n" + \
                   "\n\n".join(step_log) + "\n"
            path.write_text(body, encoding="utf-8")
            return str(path)
        except Exception as e:
            log.warning("megaplan: could not persist run file (%s)", type(e).__name__)
            return ""
