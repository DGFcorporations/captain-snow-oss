"""Captain Snow eval harness — τ-bench-style pass^k scoring.

Benchmarks the *harness* deterministically: scripted model responses in,
assertions on trajectory/dispatch/recovery out. No API keys, no network —
runs in CI and on the $5 box.

pass^k = fraction of scenarios that succeeded on ALL k trials
(τ-bench consistency metric: one lucky pass doesn't count).

Each scenario is a callable returning (ok: bool, detail: str).

Usage:
    python evals/run_evals.py            # k=3
    python evals/run_evals.py --k 5
    python evals/run_evals.py --out evals/results/latest.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "captainsnow"))
sys.path.insert(0, str(ROOT / "tests"))

from core.agent_loop import run_agent_loop
from core.orchestrator import CaptainOrchestrator
from skills.megaplan import MegaplanSkill
from conftest import FakeRouter


def _tc(name, task, call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps({"task": task})},
    }


# ── Scenarios ────────────────────────────────────────────────────────────────

def sc_tool_dispatch():
    """Model emits a tool call → invoke_skill hit once → final text returned."""
    router = FakeRouter(chat_responses=[
        {"content": "", "tool_calls": [_tc("search", "find clinics")]},
        {"content": "done", "tool_calls": []},
    ])
    calls = []

    async def invoke(name, task):
        calls.append((name, task))
        return "3 clinics"

    messages = [{"role": "user", "content": "go"}]
    out = asyncio.run(run_agent_loop(router, invoke, "sys", messages, tools=[{"x": 1}]))
    ok = (out == "done"
          and calls == [("search", {"prompt": "find clinics", "action": "execute"})]
          and messages[2]["role"] == "tool")
    return ok, f"out={out!r} calls={calls}"


def sc_malformed_args_recovers():
    """Garbage tool arguments are fed back as a tool error, not a crash."""
    bad = {"id": "c9", "type": "function", "function": {"name": "search", "arguments": ""}}
    router = FakeRouter(chat_responses=[
        {"content": "", "tool_calls": [bad]},
        {"content": "recovered", "tool_calls": []},
    ])

    async def invoke(name, task):
        return "x"

    messages = [{"role": "user", "content": "go"}]
    out = asyncio.run(run_agent_loop(router, invoke, "sys", messages))
    ok = out == "recovered" and "Could not parse arguments" in messages[2]["content"]
    return ok, f"out={out!r}"


def sc_step_budget_no_hang():
    """Model loops tool calls forever → loop stops at max_steps, returns text."""
    router = FakeRouter(chat_responses=[
        {"content": "working", "tool_calls": [_tc("search", "more")]},
    ] * 10)

    async def invoke(name, task):
        return "ok"

    start = time.monotonic()
    out = asyncio.run(run_agent_loop(
        router, invoke, "sys", [{"role": "user", "content": "x"}], max_steps=3))
    ok = out == "working" and (time.monotonic() - start) < 5
    return ok, f"out={out!r}"


def sc_provider_failure_returns_error():
    """All providers dead → error string, not an exception escaping."""
    class Boom(FakeRouter):
        async def chat(self, *a, **kw):
            raise RuntimeError("provider dead")

    async def invoke(name, task):
        return "x"

    out = asyncio.run(run_agent_loop(Boom(), invoke, "sys", [{"role": "user", "content": "x"}]))
    ok = "provider dead" in out
    return ok, f"out={out!r}"


def sc_megaplan_end_to_end(tmpdir):
    """contract → 2 steps → verify PASS → run file persisted."""
    steps = json.dumps([
        {"step": 1, "skill": "search", "task": "find", "verify": "found"},
        {"step": 2, "skill": "email_ops", "task": "send", "verify": "sent"},
    ])
    router = FakeRouter(query_responses=[
        "# Contract", steps, "PASS ok", "PASS ok", "summary text",
    ])

    class Mem:
        base_path = Path(tmpdir)

    class Orch:
        skills = {"search": 1, "email_ops": 1, "megaplan": 1}
        calls = []

        async def invoke_skill(self, name, task):
            self.calls.append(name)
            return f"{name} result"

    orch = Orch()
    skill = MegaplanSkill({}, router, Mem())
    skill._orchestrator = orch
    out = asyncio.run(skill.execute({"prompt": "goal"}))
    plans = list((Path(tmpdir) / "plans").glob("*.md"))
    ok = (orch.calls == ["search", "email_ops"]
          and "summary text" in out
          and len(plans) == 1)
    return ok, f"calls={orch.calls} plans={len(plans)}"


def sc_megaplan_replan_on_fail(tmpdir):
    """Step FAILs verification → replan produces new queue → run completes."""
    steps1 = json.dumps([{"step": 1, "skill": "search", "task": "x", "verify": "v"}])
    steps2 = json.dumps([{"step": 1, "skill": "email_ops", "task": "alt", "verify": "v"}])
    router = FakeRouter(query_responses=[
        "# Contract", steps1, "FAIL bad", steps2, "PASS ok", "summary",
    ])

    class Mem:
        base_path = Path(tmpdir)

    class Orch:
        skills = {"search": 1, "email_ops": 1}
        calls = []

        async def invoke_skill(self, name, task):
            self.calls.append(name)
            return "r"

    orch = Orch()
    skill = MegaplanSkill({}, router, Mem())
    skill._orchestrator = orch
    out = asyncio.run(skill.execute({"prompt": "goal"}))
    ok = "re-planning" in out and orch.calls == ["search", "email_ops"]
    return ok, f"calls={orch.calls}"


def sc_chokepoint_audit_log(tmpdir):
    """Every skill call goes through invoke_skill and lands in call_log."""
    cfg = {
        "skills": {"enabled": ["search", "megaplan"]},
        "agent": {"lazy_mode": True, "max_steps": 5},
        "models": {},
        "cache": {"ttl": 60},
    }
    import os
    cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        orch = CaptainOrchestrator(cfg)
        asyncio.run(orch.invoke_skill("ghost_skill", {"prompt": "x"}))
        ok = len(orch.call_log) == 1 and orch.call_log[0]["skill"] == "ghost_skill"
        return ok, f"call_log={orch.call_log}"
    finally:
        os.chdir(cwd)


SCENARIOS = [
    ("tool_dispatch", sc_tool_dispatch),
    ("malformed_args_recovers", sc_malformed_args_recovers),
    ("step_budget_no_hang", sc_step_budget_no_hang),
    ("provider_failure_returns_error", sc_provider_failure_returns_error),
    ("megaplan_end_to_end", sc_megaplan_end_to_end),
    ("megaplan_replan_on_fail", sc_megaplan_replan_on_fail),
    ("chokepoint_audit_log", sc_chokepoint_audit_log),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Captain Snow eval harness (pass^k)")
    ap.add_argument("--k", type=int, default=3, help="trials per scenario")
    ap.add_argument("--out", default="", help="write JSON report to this path")
    args = ap.parse_args()

    import tempfile
    report = {"ts": datetime.now().isoformat(), "k": args.k, "scenarios": []}

    print(f"{'scenario':<34} {'pass^1':>8} {'pass^k':>8}  detail")
    print("-" * 90)
    n_pass_k = 0
    for name, fn in SCENARIOS:
        results, details = [], []
        for trial in range(args.k):
            # ignore_cleanup_errors: ChromaDB (real orchestrator scenario) keeps
            # chroma.sqlite3 open on Windows; leftover temp files are harmless.
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
                try:
                    ok, detail = fn(td) if fn.__code__.co_argcount else fn()
                except TypeError:
                    ok, detail = fn()
                except Exception as e:
                    ok, detail = False, f"EXC {type(e).__name__}: {e}"
            results.append(bool(ok))
            if not ok:
                details.append(f"t{trial}: {detail}")
        p1 = sum(results) / len(results)
        pk = 1.0 if all(results) else 0.0
        n_pass_k += int(pk == 1.0)
        detail = "" if pk == 1.0 else "; ".join(details)[:60]
        print(f"{name:<34} {p1:>8.2f} {pk:>8.2f}  {detail}")
        report["scenarios"].append(
            {"name": name, "trials": results, "pass1": p1, "passk": pk})

    score = n_pass_k / len(SCENARIOS)
    print("-" * 90)
    print(f"pass^{args.k} suite score: {n_pass_k}/{len(SCENARIOS)} = {score:.2f}")
    report["suite_passk"] = score

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2))
        print(f"report written: {out_path}")

    return 0 if score == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
