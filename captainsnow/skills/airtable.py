import json
from .base import Skill


class AirtableSkill(Skill):
    """Airtable integration — list, create, update, and search records."""

    def _get_client(self):
        try:
            from pyairtable import Api
        except ImportError:
            raise ImportError("pyairtable is not installed. Run: pip install pyairtable")
        cfg = self.config.get("integrations", {}).get("airtable", {})
        api_key = cfg.get("api_key", "")
        if not api_key or "AIRTABLE" in api_key:
            raise ValueError("Airtable API key not configured. Add integrations.airtable.api_key to config.yaml.")
        return Api(api_key), cfg.get("base_id", "")

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "").lower()
        action = task.get("action", "")

        if action == "list" or any(w in prompt for w in ["list", "show", "get", "fetch", "read"]):
            return await self._handle_list(task)
        elif action == "create" or any(w in prompt for w in ["create", "add", "new", "insert"]):
            return await self._handle_create(task)
        elif action == "update" or any(w in prompt for w in ["update", "edit", "change", "modify"]):
            return await self._handle_update(task)
        elif action == "search" or "search" in prompt:
            return await self._handle_search(task)
        else:
            return await self._parse_and_route(task)

    async def _handle_list(self, task: dict) -> str:
        table_name = task.get("table") or await self._extract_table(task.get("prompt", ""))
        try:
            api, base_id = self._get_client()
            table = api.table(base_id, table_name)
            records = table.all(max_records=20)
            if not records:
                return f"No records found in table '{table_name}'."
            lines = [f"Records from {table_name} ({len(records)} found):"]
            for r in records[:10]:
                fields = r.get("fields", {})
                lines.append(f"  ID {r['id']}: {json.dumps(fields, default=str)[:150]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Airtable error: {e}"

    async def _handle_create(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        table_name = task.get("table") or await self._extract_table(prompt)
        fields = task.get("fields")
        if not fields:
            raw = await self.router.query(
                "Extract field name/value pairs from this Airtable record creation request. "
                "Return JSON object of field names to values.",
                prompt, max_tokens=256
            )
            try:
                fields = json.loads(raw.strip().lstrip("```json").rstrip("```"))
            except Exception:
                return f"Could not parse fields from prompt. Provide fields explicitly."
        try:
            api, base_id = self._get_client()
            table = api.table(base_id, table_name)
            record = table.create(fields)
            return f"Created record in {table_name}: ID {record['id']}"
        except Exception as e:
            return f"Airtable create error: {e}"

    async def _handle_update(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        record_id = task.get("record_id", "")
        table_name = task.get("table") or await self._extract_table(prompt)
        fields = task.get("fields", {})
        if not record_id or not fields:
            return "Provide record_id and fields to update."
        try:
            api, base_id = self._get_client()
            table = api.table(base_id, table_name)
            record = table.update(record_id, fields)
            return f"Updated record {record_id} in {table_name}."
        except Exception as e:
            return f"Airtable update error: {e}"

    async def _handle_search(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        table_name = task.get("table") or await self._extract_table(prompt)
        keyword = task.get("keyword", "")
        if not keyword:
            keyword = prompt.split("search")[-1].strip().strip("'\"")
        try:
            api, base_id = self._get_client()
            table = api.table(base_id, table_name)
            records = table.all()
            matches = [
                r for r in records
                if any(keyword.lower() in str(v).lower() for v in r.get("fields", {}).values())
            ]
            if not matches:
                return f"No records matching '{keyword}' in {table_name}."
            lines = [f"Found {len(matches)} matching records in {table_name}:"]
            for r in matches[:10]:
                lines.append(f"  {r['id']}: {json.dumps(r['fields'], default=str)[:150]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Airtable search error: {e}"

    async def _parse_and_route(self, task: dict) -> str:
        system = "Determine the Airtable action: list, create, update, or search. Reply with one word."
        action = (await self.router.query(system, task.get("prompt", ""), max_tokens=8)).strip().lower()
        if action in ["list", "create", "update", "search"]:
            task["action"] = action
            return await self.execute(task)
        return "Specify: 'list Airtable records', 'create Airtable record', 'update Airtable record', or 'search Airtable records'."


    async def _extract_table(self, prompt: str) -> str:
        system = "Extract the Airtable table name from this request. Return only the table name."
        return (await self.router.query(system, prompt, max_tokens=32)).strip()
