"""The agent loop — minimal tool-calling harness.

Model emits native `tool_calls`; each call is dispatched through the
orchestrator's `invoke_skill` chokepoint (the single place for guardrails,
rate limits, and audit logging). Results feed back as `tool` messages until
the model answers in plain text or the step budget is exhausted.

Everything is plain dicts — no SDK objects — so the loop is provider-
agnostic across the whole OpenAI-compatible cascade.
"""

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

InvokeFn = Callable[[str, dict], Awaitable[str]]


def _tool_call_dicts(tool_calls: list) -> List[dict]:
    """Normalize provider tool_call objects/dicts into plain dicts."""
    out = []
    for tc in tool_calls or []:
        if isinstance(tc, dict):
            fn = tc.get("function") or {}
            out.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", "") or ""},
            })
        else:
            fn = getattr(tc, "function", None)
            out.append({
                "id": getattr(tc, "id", "") or "",
                "type": "function",
                "function": {
                    "name": getattr(fn, "name", "") or "",
                    "arguments": getattr(fn, "arguments", "") or "",
                },
            })
    return out


def _task_from_arguments(raw: str) -> Optional[str]:
    """Extract the `task` string from a tool_call's JSON arguments.
    Tolerates the model emitting a bare string or an alternate key."""
    try:
        args = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        # Model emitted a non-JSON argument — treat the raw string as the task.
        return raw.strip() or None
    if isinstance(args, str):
        return args.strip() or None
    if isinstance(args, dict):
        for key in ("task", "prompt", "instruction", "query", "input"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


async def run_agent_loop(
    router,
    invoke_skill: InvokeFn,
    system: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[dict]] = None,
    max_steps: int = 24,
    complexity: str = "high",
) -> str:
    """Run the tool-calling loop until a plain-text reply or step exhaustion.

    `messages` is the running conversation (mutated in place — caller keeps
    the full trajectory). Returns the final assistant text.
    """
    last_text = ""

    for _ in range(max_steps):
        try:
            response = await router.chat(
                system, messages, tools=tools, complexity=complexity,
            )
        except Exception as e:
            return last_text or f"Model error: {e}"

        content = (response.get("content") or "").strip()
        tool_calls = _tool_call_dicts(response.get("tool_calls"))

        if not tool_calls:
            return content or last_text or "Done."

        # Record the assistant turn (with its tool calls) before dispatching.
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": content}
        assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)
        if content:
            last_text = content

        for tc in tool_calls:
            name = tc["function"]["name"]
            task = _task_from_arguments(tc["function"]["arguments"])
            if task is None:
                result = (
                    f"Could not parse arguments for tool '{name}'. "
                    f"Expected JSON like {{\"task\": \"what to do\"}}."
                )
            else:
                result = await invoke_skill(
                    name, {"prompt": task, "action": "execute"}
                )
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    log.warning("agent_loop: step budget (%d) exhausted", max_steps)
    return last_text or "Task took too many steps to complete."
