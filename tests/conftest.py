import sys
from pathlib import Path

import pytest

# The package uses top-level imports (core.X, skills.X, ui.X) rooted at
# captainsnow/ — put it on sys.path for the whole suite.
_PKG_ROOT = Path(__file__).parent.parent / "captainsnow"
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    """Run a test in a scratch cwd so MemoryBank writes its
    captainsnow_memory/ somewhere disposable."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class FakeRouter:
    """Scripted stand-in for ModelRouter — no network, no providers."""

    def __init__(self, chat_responses=None, query_responses=None):
        self.chat_responses = list(chat_responses or [])
        self.query_responses = list(query_responses or [])
        self.chat_calls = []
        self.query_calls = []

    async def chat(self, system, messages, tools=None, complexity="high", max_tokens=4096):
        self.chat_calls.append({"system": system, "messages": list(messages), "tools": tools})
        if self.chat_responses:
            return self.chat_responses.pop(0)
        return {"content": "done", "tool_calls": []}

    async def query(self, system, user, complexity="simple", max_tokens=1024, use_vision=False):
        self.query_calls.append({"system": system, "user": user, "complexity": complexity})
        if self.query_responses:
            return self.query_responses.pop(0)
        return ""
