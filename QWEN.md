# captain-snow-oss — AI Agent & Developer Guidelines

Repository: https://github.com/DGFcorporations/captain-snow-oss.git

## Purpose
Captain Snow is an open-source, lightweight personal AI agent and business operator built in Python 3.12.
This repository is public. All code, documentation, and configuration must remain free of credentials, private hostnames, internal paths, and non-public data.

## Workspace Boundaries
- Work strictly within this repository root. Never write or reference files outside the repository.
- Temporary or scratch files must be placed in `_agent-scratch/` (which is gitignored).

## Directory Structure
| Path | Description |
|---|---|
| `captainsnow/` | Application core, skills, and user interfaces (CLI, Web, Telegram) |
| `tests/` | Unit and integration test suite |
| `scripts/` | Tooling and utility scripts |
| `docs/` | Public documentation and guides |
| `evals/` | Agent performance evaluation fixtures |
| `_agent-scratch/` | Gitignored throwaway output |

## Code & Architecture Standards
1. **Lightweight & Free-First:** Keep memory consumption minimal. Use the standard library where possible. Default to free-tier cloud LLM providers before paid fallbacks.
2. **Secrets & Security:**
   - Real credentials must NEVER be committed.
   - All credentials must be read from environment variables via `${ENV_VAR}` expansion.
   - Fail closed: unconfigured services must refuse connections safely rather than exposing open endpoints.
3. **Reproducibility:** Dependencies must be declared in `requirements.txt` and `setup.py`.

## Verification Gates
Before committing any changes, run the verification gates:

| Gate | Command |
|---|---|
| Compile check | `python -m compileall -q captainsnow` |
| Test suite | `pytest tests/` |
| Secret scan | Verify zero API keys or tokens exist in tracked files |

Every claim of completion must be verified with an exit code of 0 from these gates.
