import asyncio

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
    # tools exist exactly for skills that loaded — a skill whose imports are
    # missing (e.g. github_ops without PyGithub) is warned+skipped, not fatal
    assert names == set(orch.skills.keys())
    assert "file_gen" in names


def test_invoke_skill_chokepoint_logs_every_call(tmp_cwd):
    orch = CaptainOrchestrator(_config())
    missing = asyncio.run(orch.invoke_skill("nope", {"prompt": "x"}))
    assert "not enabled or does not exist" in missing
    assert len(orch.call_log) == 1 and orch.call_log[0]["skill"] == "nope"
