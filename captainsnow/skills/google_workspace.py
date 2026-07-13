"""
Google Workspace skill — Sheets, Docs, Drive via Google API.
Requires a credentials.json from Google Cloud Console (OAuth 2.0 Desktop App).
Run once interactively to generate token.pickle, then it auto-refreshes.
"""

import os
import json
import pickle
from .base import Skill


class GoogleWorkspaceSkill(Skill):
    def __init__(self, config, router, memory):
        super().__init__(config, router, memory)
        self.creds = None

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "").lower()
        action = task.get("action", "")

        if "sheet" in prompt or "spreadsheet" in prompt:
            if any(w in prompt for w in ["write", "update", "add", "append", "insert"]):
                return await self._handle_write_sheet(task)
            return await self._handle_read_sheet(task)
        elif "doc" in prompt or "document" in prompt:
            if "create" in prompt or "write" in prompt:
                return await self._handle_create_doc(task)
        elif "drive" in prompt or "file" in prompt or "list" in prompt:
            return await self._handle_list_drive(task)

        return "Specify: 'read sheet', 'write sheet', 'create doc', or 'list drive files'."

    # ── Google Sheets ─────────────────────────────────────────────────────

    async def _handle_read_sheet(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        sheet_id = task.get("spreadsheet_id") or await self._extract_id(prompt, "spreadsheet")
        range_ = task.get("range", "Sheet1!A1:Z50")
        if not sheet_id:
            return "Provide a Google Sheets spreadsheet ID or URL."
        return self.read_sheet(sheet_id, range_)

    def read_sheet(self, spreadsheet_id: str, range_: str = "Sheet1!A1:Z50") -> str:
        try:
            service = self._sheets_service()
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=range_
            ).execute()
            rows = result.get("values", [])
            if not rows:
                return "Sheet is empty or range has no data."
            lines = [f"Sheet data ({len(rows)} rows):"]
            for row in rows[:20]:
                lines.append("  " + " | ".join(str(c) for c in row))
            return "\n".join(lines)
        except Exception as e:
            return f"Sheets read error: {e}"

    async def _handle_write_sheet(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        sheet_id = task.get("spreadsheet_id") or await self._extract_id(prompt, "spreadsheet")
        range_ = task.get("range", "Sheet1!A1")
        values = task.get("values")
        if not values:
            raw = await self.router.query(
                "Extract the data rows to write. Return a JSON 2D array: [[col1, col2], [val1, val2]].",
                prompt, max_tokens=256
            )
            try:
                raw = raw.strip().lstrip("```json").rstrip("```").strip()
                values = json.loads(raw)
            except Exception:
                return "Could not parse values to write."
        if not sheet_id:
            return "Provide a spreadsheet ID."
        return self.write_sheet(sheet_id, range_, values)

    def write_sheet(self, spreadsheet_id: str, range_: str, values: list) -> str:
        try:
            service = self._sheets_service()
            body = {"values": values}
            result = service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_,
                valueInputOption="RAW",
                body=body,
            ).execute()
            return f"Updated {result.get('updatedCells', '?')} cells in spreadsheet."
        except Exception as e:
            return f"Sheets write error: {e}"

    # ── Google Docs ───────────────────────────────────────────────────────

    async def _handle_create_doc(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        title = task.get("title") or await self._extract_title(prompt)
        content = task.get("content")
        if not content:
            content = await self.router.query(
                "Write the document content based on this request. Be thorough and well-structured.",
                prompt, max_tokens=1024
            )
        return self.create_doc(title, content)

    def create_doc(self, title: str, content: str) -> str:
        try:
            docs_service = self._docs_service()
            doc = docs_service.documents().create(body={"title": title}).execute()
            doc_id = doc["documentId"]
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()
            return f"Created Google Doc '{title}': https://docs.google.com/document/d/{doc_id}"
        except Exception as e:
            return f"Docs create error: {e}"

    # ── Google Drive ──────────────────────────────────────────────────────

    async def _handle_list_drive(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        query = task.get("query") or await self._extract_drive_query(prompt)
        return self.list_drive_files(query)

    def list_drive_files(self, query: str = None) -> str:
        try:
            drive_service = self._drive_service()
            params = {"pageSize": 15, "fields": "files(id, name, mimeType, modifiedTime)"}
            if query:
                params["q"] = f"name contains '{query}'"
            result = drive_service.files().list(**params).execute()
            files = result.get("files", [])
            if not files:
                return "No files found in Drive."
            lines = ["Google Drive files:"]
            for f in files:
                lines.append(f"  {f['name']} ({f['mimeType'].split('.')[-1]}) — ID: {f['id']}")
            return "\n".join(lines)
        except Exception as e:
            return f"Drive list error: {e}"

    # ── Auth ──────────────────────────────────────────────────────────────

    def authenticate(self):
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
        except ImportError:
            raise ImportError(
                "Google auth libraries not installed. Run: "
                "pip install google-auth-oauthlib google-api-python-client"
            )
        SCOPES = [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/documents",
        ]
        creds = None
        google_cfg = self.config.get("integrations", {}).get("google", {})
        token_path = google_cfg.get("token_file", "google_token.pickle")
        creds_path = google_cfg.get("credentials_file", "google_credentials.json")

        if os.path.exists(token_path):
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
        self.creds = creds
        return creds

    def _sheets_service(self):
        from googleapiclient.discovery import build
        if not self.creds:
            self.authenticate()
        return build("sheets", "v4", credentials=self.creds)

    def _docs_service(self):
        from googleapiclient.discovery import build
        if not self.creds:
            self.authenticate()
        return build("docs", "v1", credentials=self.creds)

    def _drive_service(self):
        from googleapiclient.discovery import build
        if not self.creds:
            self.authenticate()
        return build("drive", "v3", credentials=self.creds)

    async def _extract_id(self, prompt: str, type_: str) -> str:
        system = f"Extract the Google {type_} ID or URL from this request. Return only the ID (not a full URL)."
        return (await self.router.query(system, prompt, max_tokens=64)).strip()

    async def _extract_title(self, prompt: str) -> str:
        system = "Extract a concise document title from this request. Return only the title."
        return (await self.router.query(system, prompt, max_tokens=32)).strip()

    async def _extract_drive_query(self, prompt: str) -> str:
        system = "Extract a search keyword for Google Drive from this request. Return only the keyword or empty string."
        result = (await self.router.query(system, prompt, max_tokens=16)).strip()
        return result if result.lower() not in ("none", "all", "") else None
