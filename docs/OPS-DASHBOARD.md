# Ops Dashboard — dgf-ops

DGF has ONE internal operations dashboard: **dgf-ops**
(`C:\Dev\repos\dgf-ops` / `/home/chandler/Dev/repos/dgf-ops`,
remote: https://github.com/DGFcorporations/dgf-ops).

It is served at `dashboard.corporations.group` behind Cloudflare Access.
Tunnel activation is pending — do not invent a live endpoint or post
telemetry over HTTP until the tunnel + Access policy exist.

This repo does not build its own ops dashboard. Any dashboard-looking UI
in this repo is a product/customer/admin surface, not ops telemetry.

## To appear on the dashboard — file-based telemetry

Write `status/<name>.json` into the dgf-ops checkout on the same host:

- Linux:   `/home/chandler/Dev/repos/dgf-ops/status/<name>.json`
- Windows: `C:\Dev\repos\dgf-ops\status\<name>.json`

Canonical schema lives in dgf-ops `status/README.md`:

```json
{
  "agent": "<name>",
  "status": "<what it is doing>",
  "repo": "<this repo>",
  "task": "<current task>",
  "updatedAt": "<ISO-8601 UTC>",
  "pingMs": 12
}
```

- `agent` and `status` are required; the rest are optional.
- A writer updates ONLY its own file. `updatedAt` older than 24h renders
  as stale.
- `status/*.json` is gitignored in dgf-ops — status files are runtime
  drops, not repo content.
- Service health goes in `status/services.json`
  (`{"services":[{"name","port","up"}]}`), written by whatever probes the
  host. The dashboard never probes services itself.

## Conversation line

The agent swarm coordinates on Mattermost at `http://localhost:8065`
(Linux workstation). Operational chatter belongs there, not in this repo.

## Corpus

dgf-ops one-way syncs `docs/`, shared handoffs, and worklogs into Vertex
AI Search (`dgf-ops/scripts/sync-corpus.mjs`). It reads — it never writes
back. Brand tags keep DGF and VAAC corpus partitions isolated; keep
brand-clean docs in `docs/` and they reach the Oracle automatically.
