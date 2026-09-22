# captain-snow-oss — FILE PLACEMENT LAW

ROOT: `C:\Dev\repos\captain-snow-oss`
Every path below is relative to that root. This file is law, not advice.

## Purpose
Public OSS mirror of Captain Snow — lightweight personal AI agent (Python).
Synced from `repos/captain-snow` (remote `CS`). **Public repo: no internal-only
content, no credentials, no internal hostnames/paths that expose topology.**

Remote: https://github.com/DGFcorporations/captain-snow-oss.git

## THE ONE RULE
**Never write a file outside this root.** Not to Downloads, not to Desktop, not
to `C:\Users\joshc\Projects`, not to OneDrive, not to your own scratch or
cache directory (`~/.gemini`, `~/.codex`, `~/.agents`, `~/.grok`), not to a
temp folder. If a task seems to need a file outside this root, STOP and ask.

This is not style preference. Real examples from this machine:
- Two working repositories were found inside Antigravity's scratch directory.
- A 146-file copy of this project was created in `C:\Users\joshc\Projects`,
  untracked, while an empty repo of the same name sat on GitHub.
- 622 files of clinic research sat in an untracked folder for three weeks,
  invisible to git and to the owner.
None of that was malice. No agent had been told where things go.

## WHERE THINGS GO

| What you are making | Where it goes |
|---|---|
| Application source | `captainsnow/` |
| Test | `tests/` |
| Build or ops script | `scripts/` |
| Documentation | `docs/` |
| Session handoff note | `docs/handoffs/YYYY-MM-DD-topic.md` |
| Throwaway: one-off query, debug dump, scratch CSV | `_agent-scratch/` |
| Anything you cannot place | ASK. Do not guess. |

`_agent-scratch/` is gitignored and may be wiped without warning. Never put
anything there you would be sad to lose — and never put throwaway anywhere else.

## GIT
- Line endings are governed by `.gitattributes`. Do not change it.
- Before finishing: run `git status`. Untracked files you created that are
  project assets must be `git add`ed. **An untracked file does not exist to
  anyone who clones this repo.**
- If git says `Unable to create '.git/index.lock': File exists` or
  `cannot lock ref 'HEAD'`, that is a STALE LOCK. Delete the lock file and
  retry. Do not continue silently — every commit after that point is failing.
- Never `git add` anything in `_agent-scratch/`, `node_modules/`, `dist/`,
  `.venv/`, `__pycache__/`, `_to_delete/`.

## VERIFY — the honest gate
"Done" means a real command exits 0. Run it before reporting; a claim without
a green run is a false report.

| Gate | Command |
|---|---|
| Compile (CI) | `python -m compileall -q captainsnow` |
| Unit suite | `python -m pytest tests/` |
| Container (CI, heavy) | `docker build -t captain-snow:ci .` |

Environment: Python 3.12 (CI), deps from `requirements.txt`. No secrets needed
for the default gates.

## END OF SESSION — REQUIRED
1. Run `git status` and report the actual output.
2. List every file you created, with its full path.
3. State plainly whether your work is committed. If it is not, say so.
   "Done" without a commit is a false report, and it is how work here
   has been lost before.

## SHARED WORK — read before you start, write before you finish
Other agents work in these repos too. The shared folder is `C:\Dev\agents\shared`.

BEFORE: read `shared\WORKLOG.md`, then `shared\handoffs\` for this repo. If
another agent has an open line on this repo, stop and say so. Then add your line.

AFTER: update your WORKLOG line, and write
`shared\handoffs\YYYY-MM-DD-<agent>-<repo>-<topic>.md` from `_TEMPLATE.md`.
No session is finished without it.

Shared skills live in `C:\Dev\agents\shared\skills`.

## IF YOU CANNOT REACH C:\Dev — you are a cloud agent
Jules and any agent that clones this repo into its own VM cannot see
`C:\Dev\agents\shared`. It is not part of the repository.

In that case:
- Skip the WORKLOG step; you cannot read it.
- Write your handoff to `docs/handoffs/YYYY-MM-DD-<agent>-<topic>.md` in THIS repo
  and commit it with your work, so it arrives with the pull request.
- State in the PR description what you changed, what you did not finish, and
  whether anything is uncommitted.
All the file-placement rules above still apply inside the repo.
