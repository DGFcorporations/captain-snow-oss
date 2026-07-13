import smtplib
import imaplib
import email
import email.header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from .base import Skill


class EmailOpsSkill(Skill):
    """Send and read email via Zoho SMTP/IMAP (stdlib only — no extra deps)."""

    ZOHO_SMTP_HOST = "smtp.zoho.com"
    ZOHO_SMTP_PORT = 587
    ZOHO_IMAP_HOST = "imap.zoho.com"
    ZOHO_IMAP_PORT = 993

    async def execute(self, task: dict) -> str:
        prompt = task.get("prompt", "")
        action = task.get("action", "")
        lower = prompt.lower()

        if action == "send" or any(w in lower for w in ["send", "email to", "mail to", "write to"]):
            return await self._handle_send(prompt)
        elif action == "read" or any(w in lower for w in ["read", "check", "inbox", "emails", "unread"]):
            return self._read_inbox(n=10)
        elif action == "search" or "search" in lower:
            keyword = task.get("keyword", prompt.split("search")[-1].strip())
            return self._search_inbox(keyword)
        else:
            # Let LLM parse the intent
            parsed = await self._parse_email_intent(prompt)
            return parsed

    async def _handle_send(self, prompt: str) -> str:
        system = (
            "Extract email fields from this request. "
            "Return JSON: {\"to\": \"...\", \"subject\": \"...\", \"body\": \"...\"}. "
            "If body is missing, compose a professional one-paragraph email based on the intent."
        )
        import json
        try:
            raw = await self.router.query(system, prompt, max_tokens=512)
            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1].lstrip("json").strip()
            data = json.loads(raw)
            return self.send_email(data["to"], data["subject"], data["body"])
        except Exception as e:
            return f"Could not parse email intent: {e}"

    async def _parse_email_intent(self, prompt: str) -> str:
        system = "You are an email assistant. Determine if the user wants to send, read, or search email. Reply with action:send, action:read, or action:search."
        result = await self.router.query(system, prompt, max_tokens=32)
        if "send" in result:
            return await self._handle_send(prompt)
        return self._read_inbox()

    def send_email(self, to: str, subject: str, body: str) -> str:
        cfg = self.config.get("integrations", {}).get("notifications", {})
        sender = self.config.get("zoho_sender") or cfg.get("zoho_sender", "")
        password = self.config.get("zoho_app_password") or cfg.get("zoho_app_password", "")
        if not sender or not password or "ZOHO" in password.upper():
            return "Email not configured. Add zoho_sender and zoho_app_password to config.yaml."
        try:
            msg = MIMEMultipart()
            msg["From"] = sender
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))
            with smtplib.SMTP(self.ZOHO_SMTP_HOST, self.ZOHO_SMTP_PORT) as server:
                server.starttls()
                server.login(sender, password)
                server.sendmail(sender, to, msg.as_string())
            return f"Email sent to {to} — Subject: {subject}"
        except Exception as e:
            return f"Failed to send email: {e}"

    def _read_inbox(self, n: int = 10) -> str:
        sender = self.config.get("zoho_sender", "")
        password = self.config.get("zoho_app_password", "")
        if not sender or not password or "ZOHO" in password.upper():
            return "Email not configured. Add zoho_sender and zoho_app_password to config.yaml."
        try:
            with imaplib.IMAP4_SSL(self.ZOHO_IMAP_HOST, self.ZOHO_IMAP_PORT) as mail:
                mail.login(sender, password)
                mail.select("INBOX")
                _, data = mail.search(None, "ALL")
                ids = data[0].split()
                ids = ids[-n:] if len(ids) > n else ids
                messages = []
                for uid in reversed(ids):
                    _, msg_data = mail.fetch(uid, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = self._decode_header(msg.get("Subject", ""))
                    from_ = self._decode_header(msg.get("From", ""))
                    snippet = self._get_snippet(msg)
                    messages.append(f"From: {from_}\nSubject: {subject}\n{snippet}")
            return "Inbox:\n\n" + "\n---\n".join(messages)
        except Exception as e:
            return f"Failed to read inbox: {e}"

    def _search_inbox(self, keyword: str) -> str:
        sender = self.config.get("zoho_sender", "")
        password = self.config.get("zoho_app_password", "")
        if not sender or not password or "ZOHO" in password.upper():
            return "Email not configured."
        try:
            with imaplib.IMAP4_SSL(self.ZOHO_IMAP_HOST, self.ZOHO_IMAP_PORT) as mail:
                mail.login(sender, password)
                mail.select("INBOX")
                _, data = mail.search(None, f'SUBJECT "{keyword}"')
                ids = data[0].split()
                if not ids:
                    return f"No emails found with subject containing '{keyword}'."
                messages = []
                for uid in reversed(ids[-5:]):
                    _, msg_data = mail.fetch(uid, "(RFC822)")
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = self._decode_header(msg.get("Subject", ""))
                    from_ = self._decode_header(msg.get("From", ""))
                    snippet = self._get_snippet(msg)
                    messages.append(f"From: {from_}\nSubject: {subject}\n{snippet}")
            return f"Search results for '{keyword}':\n\n" + "\n---\n".join(messages)
        except Exception as e:
            return f"Failed to search inbox: {e}"

    @staticmethod
    def _decode_header(value: str) -> str:
        parts = email.header.decode_header(value)
        decoded = []
        for part, enc in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return " ".join(decoded)

    @staticmethod
    def _get_snippet(msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        return part.get_payload(decode=True).decode("utf-8", errors="replace")[:200]
                    except Exception:
                        return ""
        else:
            try:
                return msg.get_payload(decode=True).decode("utf-8", errors="replace")[:200]
            except Exception:
                return ""
        return ""
