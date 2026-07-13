import json
from .base import Skill


class SupabaseConnectorSkill(Skill):
    def __init__(self, config, router, memory):
        super().__init__(config, router, memory)
        self.client = None

    def _get_client(self):
        if self.client is None:
            try:
                from supabase import create_client
            except ImportError:
                raise ImportError("supabase is not installed. Run: pip install supabase")
            sb_cfg = self.config.get("integrations", {}).get("supabase", {})
            url = sb_cfg.get("url", "")
            key = sb_cfg.get("key", "")
            if not url or not key or "SUPABASE" in key:
                raise ValueError("Supabase not configured. Add integrations.supabase.url and key to config.yaml.")
            self.client = create_client(url, key)
        return self.client

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        action = task.get("action", "query")
        lower = prompt.lower()

        if any(w in lower for w in ["list", "show", "get", "fetch", "select", "find"]):
            return await self._handle_query(prompt)
        elif any(w in lower for w in ["insert", "create", "add", "new"]):
            return await self._handle_insert(prompt)
        elif any(w in lower for w in ["update", "edit", "change", "modify"]):
            return await self._handle_update(prompt)
        elif any(w in lower for w in ["delete", "remove"]):
            return "Delete operations require explicit confirmation. Use action='delete' with record_id."
        else:
            return await self._handle_query(prompt)

    async def _handle_query(self, prompt: str) -> str:
        """Use LLM to parse the query, then execute it dynamically."""
        system = (
            "Parse this database query request. Return JSON: "
            "{\"table\": \"table_name\", \"filters\": {\"column\": \"value\"}, \"limit\": 10}. "
            "Only include filters that were explicitly mentioned. table is required."
        )
        try:
            raw = await self.router.query(system, prompt, max_tokens=128)
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            parsed = json.loads(raw)
        except Exception:
            return "Could not parse query. Try: 'list all records from customers' or 'show users where status is active'."

        table = parsed.get("table", "")
        if not table or not self._is_safe_identifier(table):
            return f"Table name '{table}' is invalid or missing."

        filters = parsed.get("filters", {})
        limit = min(int(parsed.get("limit", 10)), 100)

        try:
            client = self._get_client()
            query = client.table(table).select("*").limit(limit)
            for col, val in filters.items():
                if self._is_safe_identifier(col):
                    query = query.eq(col, val)
            result = query.execute()
            rows = result.data
            if not rows:
                return f"No records found in '{table}' matching your query."
            lines = [f"Found {len(rows)} record(s) in '{table}':"]
            for row in rows[:10]:
                lines.append(f"  {json.dumps(row, default=str)[:200]}")
            return "\n".join(lines)
        except Exception as e:
            return f"Supabase query error: {e}"

    async def _handle_insert(self, prompt: str) -> str:
        system = (
            "Parse this insert request. Return JSON: "
            "{\"table\": \"table_name\", \"data\": {\"field\": \"value\"}}."
        )
        try:
            raw = await self.router.query(system, prompt, max_tokens=256)
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            parsed = json.loads(raw)
            table = parsed.get("table", "")
            data = parsed.get("data", {})
            if not table or not self._is_safe_identifier(table):
                return "Invalid table name."
            client = self._get_client()
            result = client.table(table).insert(data).execute()
            return f"Inserted record into '{table}': {json.dumps(result.data[0] if result.data else {}, default=str)[:200]}"
        except Exception as e:
            return f"Supabase insert error: {e}"

    async def _handle_update(self, prompt: str) -> str:
        system = (
            "Parse this update request. Return JSON: "
            "{\"table\": \"...\", \"match\": {\"col\": \"val\"}, \"data\": {\"field\": \"value\"}}."
        )
        try:
            raw = await self.router.query(system, prompt, max_tokens=256)
            raw = raw.strip().lstrip("```json").rstrip("```").strip()
            parsed = json.loads(raw)
            table = parsed.get("table", "")
            match = parsed.get("match", {})
            data = parsed.get("data", {})
            if not table or not self._is_safe_identifier(table):
                return "Invalid table name."
            client = self._get_client()
            query = client.table(table).update(data)
            for col, val in match.items():
                if self._is_safe_identifier(col):
                    query = query.eq(col, val)
            result = query.execute()
            return f"Updated {len(result.data)} record(s) in '{table}'."
        except Exception as e:
            return f"Supabase update error: {e}"

    @staticmethod
    def _is_safe_identifier(name: str) -> bool:
        """Allow only alphanumeric + underscore table/column names to prevent injection."""
        return bool(name) and all(c.isalnum() or c == "_" for c in name)
