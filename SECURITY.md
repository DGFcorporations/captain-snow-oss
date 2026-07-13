# Security Policy

Captain Snow is an agent that can hold live credentials (Stripe, email,
databases). Security reports are taken seriously.

## Reporting a vulnerability

Please report vulnerabilities privately via
[GitHub Security Advisories](../../security/advisories/new) rather than
opening a public issue. You'll get a response as quickly as possible, and
credit in the fix's release notes if you want it.

## Design principles

- **Fail closed** — unconfigured auth means nobody gets in, not everybody.
  The Telegram bot ignores all messages until `TELEGRAM_OWNER_ID` is set.
- **Token-gated web chat** — `POST /chat` requires a Bearer token when
  `CAPTAINSNOW_WEB_TOKEN` is set; boot logs warn loudly when it isn't.
- **No secrets in the repo or config** — all credentials come from
  environment variables via `${VAR}` expansion.
- **No arbitrary code execution skill** — by design. Don't add one in a PR.
- **Log hygiene** — HTTP client logging that would echo bot tokens is
  suppressed.

## Scope

The threat model assumes Captain Snow runs on a host you control, exposed
to the internet at most through the web chat port. If you expose the
container another way (open Docker API, shared host, etc.), that's outside
the app's control.
