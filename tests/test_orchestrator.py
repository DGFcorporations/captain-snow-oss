import asyncio
from collections import deque

from core.orchestrator import CaptainOrchestrator, _SKILL_REGISTRY


def _config(enabled=("search", "megaplan")):
    return {
        "skills": {"enabled": list(enabled)},
        "agent": {"lazy_mode": True, "max_steps": 5},
        "models": {},
        "cache": {"ttl": 60},
    }


def test_registry_maps_planner_alias_to_megaplan():
    assert _SKILL_REGISTRY["planner"] == ("skills.megaplan", "MegaplanSkill")
    assert _SKILL_REGISTRY["megaplan"] == ("skills.megaplan", "MegaplanSkill")


def test_tools_built_from_enabled_skills(tmp_cwd):
    orch = CaptainOrchestrator(_config())
    names = {t["function"]["name"] for t in orch.tools}
    assert "megaplan" in names
    assert names == set(orch.skills.keys())
    assert "file_gen" not in names
    assert "github_ops" not in names


def test_empty_enabled_list_does_not_force_enable_skills():
    orch = CaptainOrchestrator.__new__(CaptainOrchestrator)
    orch.config = {"skills": {"enabled": []}}
    orch.skills = {}
    orch._load_skills()
    assert orch.skills == {}
    assert orch.config["skills"]["enabled"] == []


def test_omitted_enabled_key_does_not_force_enable_skills():
    orch = CaptainOrchestrator.__new__(CaptainOrchestrator)
    orch.config = {"skills": {}}
    orch.skills = {}
    orch._load_skills()
    assert orch.skills == {}


def test_invoke_skill_chokepoint_logs_every_call(tmp_cwd):
    orch = CaptainOrchestrator(_config())
    missing = asyncio.run(orch.invoke_skill("nope", {"prompt": "x"}))
    assert "not enabled or does not exist" in missing
    assert len(orch.call_log) == 1 and orch.call_log[0]["skill"] == "nope"


def test_invoke_skill_normalizes_structured_results_and_logs_failure():
    class _ResultSkill:
        async def execute(self, task):
            return {"status": "error", "details": "not created"}

    orch = CaptainOrchestrator.__new__(CaptainOrchestrator)
    orch.skills = {"file_gen": _ResultSkill()}
    orch.call_log = deque(maxlen=200)
    result = asyncio.run(orch.invoke_skill("file_gen", {"prompt": "create"}))
    assert result == '{"details": "not created", "status": "error"}'
    assert orch.call_log[-1]["ok"] is False
    assert orch.call_log[-1]["result_len"] == len(result)
