# core/memory.py
import aiofiles
import json
import sqlite_utils
import chromadb
import chromadb.utils.embedding_functions as embedding_functions
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pathlib import Path


class MemoryBank:
    def __init__(self, config: dict, router=None):
        self.config = config
        self.router = router  # Reuse the caller's router; only create one if not provided
        self.base_path = Path("captainsnow_memory")
        self.base_path.mkdir(exist_ok=True)

        self.db = sqlite_utils.Database(self.base_path / "memory.db")
        self._init_db()

        # Pin embedding model explicitly — prevents silent upgrades to heavier models
        _embed_fn = embedding_functions.DefaultEmbeddingFunction()
        self.chroma_client = chromadb.PersistentClient(path=str(self.base_path / "chroma"))
        self.conversation_collection = self.chroma_client.get_or_create_collection(
            "conversations", embedding_function=_embed_fn
        )
        self.knowledge_collection = self.chroma_client.get_or_create_collection(
            "knowledge", embedding_function=_embed_fn
        )

        self.files_path = self.base_path / "files"
        self.files_path.mkdir(exist_ok=True)
        self.cache_ttl = config.get("cache", {}).get("ttl", 3600)

    def _get_router(self):
        """Return the shared router, creating one lazily only if not injected."""
        if self.router is None:
            from core.model_router import ModelRouter
            self.router = ModelRouter(self.config)
        return self.router

    def _init_db(self):
        self.db["episodes"].create({
            "id": int,
            "timestamp": str,
            "summary": str,
            "key_topics": str,
            "raw_transcript": str,
        }, pk="id", if_not_exists=True)

        self.db["facts"].create({
            "key": str,
            "value": str,
            "updated": str,
        }, pk="key", if_not_exists=True)

        self.db["cache"].create({
            "key": str,
            "value": str,
            "timestamp": float,
        }, pk="key", if_not_exists=True)

        self.db["user_prefs"].create({
            "key": str,
            "value": str,
        }, pk="key", if_not_exists=True)

        self.db["file_index"].create({
            "filename": str,
            "path": str,
            "timestamp": str,
        }, pk="filename", if_not_exists=True)

    # ── Conversation Logging ──────────────────────────────────────────────

    async def log_interaction(self, user_msg: str, assistant_msg: str):
        timestamp = datetime.now().isoformat()
        today = datetime.now().strftime("%Y-%m-%d")
        transcript_file = self.base_path / f"transcript_{today}.jsonl"
        async with aiofiles.open(transcript_file, "a") as f:
            await f.write(json.dumps({
                "timestamp": timestamp,
                "user": user_msg,
                "assistant": assistant_msg,
            }) + "\n")

    # ── Nightly Consolidation ─────────────────────────────────────────────

    async def consolidate_daily_memory(self):
        """Summarise today's conversation into an episode and embed it."""
        today = datetime.now().strftime("%Y-%m-%d")
        transcript_file = self.base_path / f"transcript_{today}.jsonl"
        if not transcript_file.exists():
            return

        interactions = []
        async with aiofiles.open(transcript_file, "r") as f:
            async for line in f:
                line = line.strip()
                if line:
                    interactions.append(json.loads(line))

        if not interactions:
            return

        full_text = "".join(
            f"User: {i['user']}\nAssistant: {i['assistant']}\n"
            for i in interactions
        )
        summary_prompt = (
            "Summarise the following day's conversation between a user and CaptainSnow AI. "
            "Capture key decisions, business updates, and tasks. Be brief.\n\n"
            f"{full_text[-3000:]}\n\nSummary:"
        )
        router = self._get_router()
        summary = await router.query("You are a meticulous note-taker.", summary_prompt)

        topics = await self._extract_topics(summary)

        episode_id = int(datetime.now().timestamp())
        self.db["episodes"].insert({
            "id": episode_id,
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "key_topics": ",".join(topics),
            "raw_transcript": full_text[-5000:],
        })

        self.conversation_collection.add(
            documents=[summary],
            ids=[str(episode_id)],
            metadatas=[{"date": today, "topics": ",".join(topics)}],
        )

        await self._extract_facts_from_transcript(interactions)
        transcript_file.unlink()

    async def _extract_topics(self, text: str) -> List[str]:
        router = self._get_router()
        prompt = f"Extract up to 5 key topics (single words or short phrases) from this summary: {text}"
        result = await router.query("You extract topics.", prompt, max_tokens=64)
        return [t.strip() for t in result.split(",") if t.strip()]

    async def _extract_facts_from_transcript(self, interactions: List[dict]):
        # Case-insensitive check for "remember ..." statements
        statements = [i["user"] for i in interactions if i["user"].lower().startswith("remember")]
        if not statements:
            return
        router = self._get_router()
        fact_prompt = (
            "Extract user preferences or business facts from these statements. "
            "Return a JSON list of {\"key\": \"value\"}.\n" + "\n".join(statements)
        )
        try:
            result = await router.query("You extract structured facts.", fact_prompt)
            facts = json.loads(result)
            for fact in facts:
                self.set_fact(fact["key"], fact["value"])
        except Exception:
            pass

    # ── Semantic Recall ───────────────────────────────────────────────────

    def recall_relevant_context(self, query: str, n: int = 3) -> str:
        episodes = []
        try:
            ep_results = self.conversation_collection.query(query_texts=[query], n_results=n)
            if ep_results["documents"] and ep_results["documents"][0]:
                episodes = ep_results["documents"][0]
        except Exception:
            pass

        facts = []
        try:
            fact_results = self.knowledge_collection.query(query_texts=[query], n_results=3)
            if fact_results["documents"] and fact_results["documents"][0]:
                facts = fact_results["documents"][0]
        except Exception:
            pass

        context = "Relevant past context:\n"
        for ep in episodes:
            context += f"- {ep[:200]}\n"
        for fact in facts:
            context += f"- Fact: {fact}\n"

        # Compress if too long for the local model's context window
        return self.compress_context(context)

    def compress_context(self, text: str, max_chars: int = 800) -> str:
        """If recalled context is long, summarize it to stay within the local model's window."""
        if len(text) <= max_chars:
            return text
        router = self._get_router()
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't await here synchronously — just truncate
                return text[:max_chars] + "… [truncated]"
            summary = loop.run_until_complete(
                router.query(
                    "Summarize this context in under 400 characters, keeping key facts.",
                    text, max_tokens=128
                )
            )
            return "Compressed context:\n" + summary
        except Exception:
            return text[:max_chars] + "… [truncated]"

    # ── Facts / Knowledge ─────────────────────────────────────────────────

    def set_fact(self, key: str, value: str):
        now = datetime.now().isoformat()
        self.db["facts"].upsert({"key": key, "value": value, "updated": now}, pk="key")
        self.knowledge_collection.upsert(
            documents=[value],
            ids=[key],
            metadatas=[{"key": key, "updated": now}],
        )

    def get_fact(self, key: str) -> Optional[str]:
        try:
            row = self.db["facts"].get(key)
            return row["value"] if row else None
        except Exception:
            return None

    def list_facts(self) -> List[Dict]:
        return list(self.db["facts"].rows)

    # ── File Store ────────────────────────────────────────────────────────

    async def save_file(self, filename: str, content: bytes):
        path = self.files_path / filename
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)
        self.db["file_index"].upsert({
            "filename": filename,
            "path": str(path),
            "timestamp": datetime.now().isoformat(),
        }, pk="filename")

    def get_file_path(self, filename: str) -> Optional[Path]:
        path = self.files_path / filename
        return path if path.exists() else None

    # ── Morning Briefing ──────────────────────────────────────────────────

    async def morning_recap(self) -> str:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        rows = list(self.db["episodes"].rows_where("timestamp LIKE ?", (f"{yesterday}%",)))
        episode = rows[0] if rows else None
        recap = "Here's what we did yesterday:\n"
        if episode:
            recap += episode["summary"] + "\n"
        else:
            recap += "No activity recorded yesterday.\n"
        facts = self.list_facts()
        if facts:
            recap += "\nRemembered facts:\n"
            for f in facts:
                recap += f"- {f['key']}: {f['value']}\n"
        return recap

    # ── Cache ─────────────────────────────────────────────────────────────

    def cache_get(self, key: str) -> Optional[str]:
        try:
            row = self.db["cache"].get(key)
            if row and (datetime.now().timestamp() - row["timestamp"] < self.cache_ttl):
                return row["value"]
        except Exception:
            pass
        return None

    def cache_set(self, key: str, value: str):
        self.db["cache"].upsert({
            "key": key,
            "value": value,
            "timestamp": datetime.now().timestamp(),
        }, pk="key")

    def get_pref(self, key: str, default=None):
        try:
            row = self.db["user_prefs"].get(key)
            return row["value"] if row else default
        except Exception:
            return default

    def set_pref(self, key: str, value: str):
        self.db["user_prefs"].upsert({"key": key, "value": value}, pk="key")


# Alias for compatibility
Memory = MemoryBank
