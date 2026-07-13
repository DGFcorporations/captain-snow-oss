"""
Watchers — real uptime + activity monitoring with Telegram alerts.

When lazy_mode is false (or explicitly started via `captainsnow monitor`),
the daemon checks every cycle_hours:
  - URL uptime for any URLs in config.monitor_urls
  - New Stripe charges since the last check
  - New Airtable records since the last check
  - Sends Telegram alerts on anything noteworthy
"""

import asyncio
import json
import sqlite_utils
import httpx
from datetime import datetime
from pathlib import Path
from core.model_router import ModelRouter
from core.memory import Memory
from .base import Skill


class WatchersSkill(Skill):
    async def execute(self, task: dict) -> str:
        # Default status reporting regardless of the action string
        return "All watchdogs standing by. Run `captainsnow monitor` to start the daemon."


class MonitoringDaemon:
    def __init__(self, config):
        self.config = config
        self.router = ModelRouter(config)
        self.cycle_hours = config.get("cycle_hours", 12)
        # Persist last-seen IDs so we don't re-alert on old data
        self._state_path = Path("captainsnow_memory") / "watcher_state.json"
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except Exception:
                pass
        return {"last_stripe_charge": None, "last_airtable_ids": {}}

    def _save_state(self):
        self._state_path.parent.mkdir(exist_ok=True)
        self._state_path.write_text(json.dumps(self._state))

    def run(self):
        lazy_mode = self.config.get("agent", {}).get("lazy_mode", True)
        if lazy_mode:
            print(
                "MonitoringDaemon: lazy_mode is enabled.\n"
                "Set agent.lazy_mode: false in config.yaml to run continuously, "
                "or use `captainsnow monitor` to run a single check now."
            )
            asyncio.run(self._run_checks())
            return
        asyncio.run(self._run_loop())

    async def _run_loop(self):
        print(f"Monitoring Daemon started — checking every {self.cycle_hours}h.")
        while True:
            await self._run_checks()
            await asyncio.sleep(self.cycle_hours * 3600)

    async def _run_checks(self):
        alerts = []

        # 1. URL uptime checks
        monitor_urls = self.config.get("monitor_urls", [])
        if monitor_urls:
            url_alerts = await self._check_urls(monitor_urls)
            alerts.extend(url_alerts)

        # 2. Stripe new charges
        stripe_alerts = await self._check_stripe()
        alerts.extend(stripe_alerts)

        # 3. Airtable new records
        airtable_alerts = await self._check_airtable()
        alerts.extend(airtable_alerts)

        # 4. Nightly memory consolidation
        try:
            memory = Memory(self.config, router=self.router)
            await memory.consolidate_daily_memory()
        except Exception as e:
            print(f"Memory consolidation error: {e}")

        # 5. Send Telegram alerts
        if alerts:
            message = "🔔 Captain Snow Alert\n\n" + "\n\n".join(alerts)
            await self._telegram_alert(message)
            print(message)
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] All clear — no alerts.")

        self._save_state()

    # ── Uptime monitoring ─────────────────────────────────────────────────

    async def _check_urls(self, urls: list) -> list:
        alerts = []
        async with httpx.AsyncClient(timeout=10) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    if resp.status_code >= 400:
                        alerts.append(f"⚠️ URL DOWN: {url} returned HTTP {resp.status_code}")
                except Exception as e:
                    alerts.append(f"⚠️ URL UNREACHABLE: {url} — {type(e).__name__}")
        return alerts

    # ── Stripe monitoring ─────────────────────────────────────────────────

    async def _check_stripe(self) -> list:
        alerts = []
        stripe_key = self.config.get("integrations", {}).get("stripe", {}).get("api_key", "")
        if not stripe_key or "STRIPE" in stripe_key:
            return alerts
        try:
            import stripe
            stripe.api_key = stripe_key
            charges = stripe.Charge.list(limit=5)
            new_charges = []
            last_seen = self._state.get("last_stripe_charge")
            for charge in charges.data:
                if last_seen and charge.id == last_seen:
                    break
                new_charges.append(charge)
            if new_charges:
                self._state["last_stripe_charge"] = charges.data[0].id
                total = sum(c.amount for c in new_charges) / 100
                alerts.append(
                    f"💰 {len(new_charges)} new Stripe charge(s) — ${total:.2f} total\n"
                    + "\n".join(f"  • ${c.amount/100:.2f} from {c.billing_details.name or 'unknown'}" for c in new_charges)
                )
        except Exception as e:
            print(f"Stripe check error: {e}")
        return alerts

    # ── Airtable monitoring ───────────────────────────────────────────────

    async def _check_airtable(self) -> list:
        alerts = []
        at_cfg = self.config.get("integrations", {}).get("airtable", {})
        api_key = at_cfg.get("api_key", "")
        base_id = at_cfg.get("base_id", "")
        monitor_tables = at_cfg.get("monitor_tables", [])
        if not api_key or "AIRTABLE" in api_key or not monitor_tables:
            return alerts
        try:
            from pyairtable import Api
            api = Api(api_key)
            for table_name in monitor_tables:
                table = api.table(base_id, table_name)
                records = table.all(max_records=20)
                current_ids = {r["id"] for r in records}
                last_ids = set(self._state.get("last_airtable_ids", {}).get(table_name, []))
                new_ids = current_ids - last_ids
                if new_ids and last_ids:  # skip on first run (no baseline)
                    alerts.append(f"📋 {len(new_ids)} new record(s) in Airtable table '{table_name}'")
                self._state.setdefault("last_airtable_ids", {})[table_name] = list(current_ids)
        except Exception as e:
            print(f"Airtable check error: {e}")
        return alerts

    # ── Telegram ──────────────────────────────────────────────────────────

    async def _telegram_alert(self, message: str):
        token = self.config.get("telegram_bot_token", "")
        chat_id = self.config.get("telegram_chat_id", "")
        if not token or not chat_id or "TELEGRAM" in token:
            return
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": message[:4000], "parse_mode": "Markdown"},
                    timeout=10,
                )
        except Exception as e:
            print(f"Telegram alert failed: {e}")
