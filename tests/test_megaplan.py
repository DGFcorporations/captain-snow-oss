import asyncio
import json
from pathlib import Path

from conftest import FakeRouter
from skills.megaplan import MegaplanSkill


class _Memory:
    """Minimal stand-in exposing base_path like MemoryBank."""
    def __init__(self, base_path):
        self.base_path = Path(base_path)


class _Orchestrator:
    """Records invoke_skill calls; returns scripted results per skill."""
    def __init__(self, results=None):
        self.skills = {"search": object(), "email_ops": object(), "megaplan": object()}
        self.results = results or {}
        self.calls = []

    async def invoke_skill(self, name, task):
        self.calls.append((name, task))
        return self.results.get(name, f"{name} result")


def _steps_json(steps):
    return json.dumps(steps)


def test_happy_path_contract_steps_verify_persist(tmp_cwd):
    router = FakeRouter(query_responses=[
        "# Contract\n- do the thing",                       # contract
        _steps_json([                                       # steps
            {"step": 1, "skill": "search", "task": "find it", "verify": "results found"},
            {"step": 2, "skill": "email_ops", "task": "send it", "verify": "sent"},
        ]),
        "PASS found 3 results",                              # verify step 1
        "PASS sent",                                         # verify step 2
        "all done",                                          # summary
    ])
    orch = _Orchestrator()
    skill = MegaplanSkill({}, router, _Memory(tmp_cwd))
    skill._orchestrator = orch

    out = asyncio.run(skill.execute({"prompt": "find clinics and email me"}))

    assert "# Megaplan run" in out and "all done" in out
    assert [c[0] for c in orch.calls] == ["search", "email_ops"]
    runs = list((tmp_cwd / "plans").glob("*.md"))
    assert len(runs) == 1 and "find clinics" in runs[0].read_text()


def test_failed_verify_triggers_replan(tmp_cwd):
    router = FakeRouter(query_responses=[
        "# Contract",
        _steps_json([{"step": 1, "skill": "search", "task": "x", "verify": "v"}]),
        "FAIL empty result",                                 # verify: fail
        _steps_json([{"step": 1, "skill": "email_ops", "task": "alt", "verify": "v"}]),  # replan
        "PASS ok",                                           # verify new step
        "summary",
    ])
    orch = _Orchestrator()
    skill = MegaplanSkill({}, router, _Memory(tmp_cwd))
    skill._orchestrator = orch

    out = asyncio.run(skill.execute({"prompt": "goal"}))

    assert "re-planning" in out
    assert [c[0] for c in orch.calls] == ["search", "email_ops"]


def test_no_steps_returns_graceful_message(tmp_cwd):
    router = FakeRouter(query_responses=["# Contract", "not json at all"])
    skill = MegaplanSkill({}, router, _Memory(tmp_cwd))
    skill._orchestrator = _Orchestrator()

    out = asyncio.run(skill.execute({"prompt": "vague"}))
    assert "Could not decompose" in out


def test_empty_goal_rejected(tmp_cwd):
    skill = MegaplanSkill({}, FakeRouter(), _Memory(tmp_cwd))
    assert "Give me a goal" in asyncio.run(skill.execute({"prompt": "  "}))


def test_no_orchestrator_reference_errors_in_step(tmp_cwd):
    router = FakeRouter(query_responses=[
        "# Contract",
        _steps_json([{"step": 1, "skill": "search", "task": "x", "verify": "v"}]),
        "summary",
    ])
    skill = MegaplanSkill({}, router, _Memory(tmp_cwd))  # _orchestrator stays None
    out = asyncio.run(skill.execute({"prompt": "goal"}))
    assert "no orchestrator reference" in out
