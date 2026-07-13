# Contributing to Captain Snow

Ahoy! PRs, issues, and ideas are all welcome. This page keeps the ship tidy.

## Ground rules

1. **Lightweight is the whole point.** Every new dependency must earn its
   place in RAM. If a feature can be done with the standard library or an
   existing dependency, do it that way. PRs that add heavy dependencies for
   marginal features will be asked to slim down.
2. **Free-first.** Features should work on free-tier providers before paid
   ones. Paid-only integrations belong behind optional config.
3. **Secrets are env-only.** Nothing in the repo should ever need a real
   API key. Config references secrets via `${ENV_VAR}` expansion
   (see `core/profile.py`). CI will not have secrets, and neither should
   your tests.
4. **Fail closed.** If a feature touches auth or credentials, the
   unconfigured state must be the safe state (see the Telegram bot for the
   pattern).

## Adding a skill

1. Create `captainsnow/skills/your_skill.py`:

```python
from .base import Skill

class YourSkill(Skill):
    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        # do the thing
        return "result the user will read"
```

2. Register it in `core/orchestrator.py` (`_SKILL_REGISTRY`), and add an
   intent keyword in `_INTENT_SKILL_MAP` if it should be directly routable.
3. Add it to `skills.enabled` in `config.example.yaml` with any config it
   needs (env-var references only).
4. Update the skills table in `README.md`.

## Dev setup

```bash
git clone https://github.com/DGFcorporations/captain-snow-oss.git
cd captain-snow-oss
cp config.example.yaml config.yaml
pip install -e .
captainsnow chat "test"
```

## Pull requests

- Keep PRs focused — one feature or fix per PR.
- Describe *why*, not just *what*.
- `python -m compileall captainsnow` must pass (CI checks this).
- If you changed behavior, update the README.

## Reporting bugs

Open an issue with: what you did, what you expected, what happened, and
your setup (Docker or bare Python, which providers configured). Logs help —
but **scrub your tokens before pasting**.

## Security issues

Please do NOT open public issues for security vulnerabilities — see
[SECURITY.md](SECURITY.md).
