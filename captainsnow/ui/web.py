"""
FastAPI web chat UI for Captain Snow.

Serves a minimal chat page at GET / and a JSON chat endpoint at POST /chat
on port 8000 (put a reverse proxy with HTTPS in front for production).
"""

import logging
import os
import secrets

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.orchestrator import CaptainOrchestrator
from core.profile import load_config


config = load_config()
orchestrator = CaptainOrchestrator(config)

# The agent holds Stripe/email/Airtable/Supabase credentials — the chat
# endpoint must not be open to the whole internet. Set CAPTAINSNOW_WEB_TOKEN
# in the environment; the web UI asks for it once and remembers it.
_WEB_TOKEN = os.environ.get("CAPTAINSNOW_WEB_TOKEN", "")
if not _WEB_TOKEN:
    logging.getLogger("captainsnow.web").warning(
        "CAPTAINSNOW_WEB_TOKEN is not set — POST /chat is UNAUTHENTICATED. "
        "Set it as an environment variable to lock down the web chat."
    )

app = FastAPI(title="Captain Snow", version="0.2.0")

# Comma-separated list of allowed origins, e.g. "https://app.example.com,https://x.example.com"
_cors_origins = [o.strip() for o in os.environ.get("CAPTAINSNOW_CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, authorization: str = Header(default="")):
    if _WEB_TOKEN:
        supplied = authorization.removeprefix("Bearer ").strip()
        if not secrets.compare_digest(supplied, _WEB_TOKEN):
            raise HTTPException(status_code=401, detail="invalid or missing token")
    text = (req.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    reply = await orchestrator.process_request(text)
    return ChatResponse(reply=reply)


_CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Captain Snow</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0b0f14; color: #e6edf3; height: 100vh; display: flex; flex-direction: column; }
  header { padding: 12px 16px; background: #11161d; border-bottom: 1px solid #1f2630; font-weight: 600; }
  #log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
  .msg { max-width: 75%; padding: 10px 14px; border-radius: 14px; white-space: pre-wrap; line-height: 1.4; }
  .user { align-self: flex-end; background: #2563eb; color: #fff; border-bottom-right-radius: 4px; }
  .bot  { align-self: flex-start; background: #1c2430; color: #e6edf3; border-bottom-left-radius: 4px; }
  .meta { font-size: 12px; opacity: 0.6; padding: 0 16px; }
  form { display: flex; gap: 8px; padding: 12px; background: #11161d; border-top: 1px solid #1f2630; }
  input { flex: 1; padding: 10px 12px; border-radius: 10px; border: 1px solid #2a3340;
          background: #0b0f14; color: #e6edf3; font-size: 15px; }
  input:focus { outline: none; border-color: #2563eb; }
  button { padding: 10px 18px; border-radius: 10px; border: 0; background: #2563eb; color: #fff;
           font-weight: 600; cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: wait; }
</style>
</head>
<body>
<header>Captain Snow</header>
<div id="log"></div>
<div class="meta" id="status"></div>
<form id="f">
  <input id="m" placeholder="Talk to the Captain..." autocomplete="off" autofocus />
  <button id="send" type="submit">Send</button>
</form>
<script>
const log = document.getElementById('log');
const f = document.getElementById('f');
const m = document.getElementById('m');
const send = document.getElementById('send');
const status = document.getElementById('status');

function add(role, text) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = m.value.trim();
  if (!text) return;
  add('user', text);
  m.value = '';
  send.disabled = true;
  status.textContent = 'Captain is thinking...';
  try {
    let r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + (localStorage.getItem('cs_token') || '')},
      body: JSON.stringify({message: text}),
    });
    if (r.status === 401) {
      const t = prompt('Access token for Captain Snow:');
      if (t) {
        localStorage.setItem('cs_token', t.trim());
        r = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + t.trim()},
          body: JSON.stringify({message: text}),
        });
      }
    }
    const data = await r.json();
    add('bot', data.reply || data.detail || '(no reply)');
  } catch (err) {
    add('bot', 'Error: ' + err.message);
  } finally {
    send.disabled = false;
    status.textContent = '';
    m.focus();
  }
});
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return _CHAT_HTML
