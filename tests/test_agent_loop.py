import asyncio
import json

from conftest import FakeRouter
from core.agent_loop import run_agent_loop, _task_from_arguments, _tool_call_dicts


def _tc(name, task, call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps({"task": task})},
    }


def test_plain_text_reply_ends_loop():
    router = FakeRouter(chat_responses=[{"content": "hello captain", "tool_calls": []}])
    calls = []

    async def invoke(name, task):
        calls.append(name)
        return "result"

    out = asyncio.run(run_agent_loop(router, invoke, "sys", [{"role": "user", "content": "hi"}]))
    assert out == "hello captain"
    assert calls == []


def test_tool_call_dispatches_and_threads_result():
    router = FakeRouter(chat_responses=[
        {"content": "", "tool_calls": [_tc("search", "find clinics")]},
        {"content": "found them", "tool_calls": []},
    ])
    invoked = []

    async def invoke(name, task):
        invoked.append((name, task))
        return "3 clinics"

    messages = [{"role": "user", "content": "find clinics"}]
    out = asyncio.run(run_agent_loop(router, invoke, "sys", messages, tools=[{"x": 1}]))

    assert out == "found them"
    assert invoked == [("search", {"prompt": "find clinics", "action": "execute"})]
    # assistant turn with tool_calls + tool result were appended
    assert messages[1]["role"] == "assistant" and messages[1]["tool_calls"]
    assert messages[2] == {"role": "tool", "tool_call_id": "call_1", "content": "3 clinics"}


def test_malformed_arguments_feed_back_as_tool_error():
    bad = {"id": "c9", "type": "function", "function": {"name": "search", "arguments": ""}}
    router = FakeRouter(chat_responses=[
        {"content": "", "tool_calls": [bad]},
        {"content": "recovered", "tool_calls": []},
    ])

    async def invoke(name, task):
        return "should not be called"

    messages = [{"role": "user", "content": "go"}]
    out = asyncio.run(run_agent_loop(router, invoke, "sys", messages))
    assert out == "recovered"
    assert "Could not parse arguments" in messages[2]["content"]


def test_step_budget_exhaustion_returns_last_text():
    router = FakeRouter(chat_responses=[
        {"content": "still working", "tool_calls": [_tc("search", "more")]},
        {"content": "still working", "tool_calls": [_tc("search", "more")]},
    ])

    async def invoke(name, task):
        return "ok"

    out = asyncio.run(run_agent_loop(router, invoke, "sys", [{"role": "user", "content": "x"}], max_steps=2))
    assert out == "still working"


def test_router_error_returns_last_text_or_error():
    class Boom(FakeRouter):
        async def chat(self, *a, **kw):
            raise RuntimeError("provider dead")

    async def invoke(name, task):
        return "x"

    out = asyncio.run(run_agent_loop(Boom(), invoke, "sys", [{"role": "user", "content": "x"}]))
    assert "provider dead" in out


def test_task_from_arguments_variants():
    assert _task_from_arguments('{"task": "do x"}') == "do x"
    assert _task_from_arguments('{"prompt": "do y"}') == "do y"
    assert _task_from_arguments("not json") == "not json"
    assert _task_from_arguments("") is None
    assert _task_from_arguments('{"unrelated": 1}') is None


def test_tool_call_dicts_normalizes_objects_and_dicts():
    class Fn:
        name = "search"
        arguments = '{"task": "x"}'

    class TC:
        id = "abc"
        function = Fn()

    out = _tool_call_dicts([TC(), {"id": "d", "function": {"name": "s", "arguments": "{}"}}])
    assert out[0] == {"id": "abc", "type": "function", "function": {"name": "search", "arguments": '{"task": "x"}'}}
    assert out[1]["function"]["name"] == "s"
