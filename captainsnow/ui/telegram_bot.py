"""
Telegram bot — long-poll loop that routes every message through the orchestrator.

Filters by telegram_owner_id so only you can talk to him. Group chats and
strangers are ignored. Shares memory + skills with the web UI through the
single shared CaptainOrchestrator instance.
"""

import logging

from core.orchestrator import CaptainOrchestrator

log = logging.getLogger(__name__)


async def run_telegram_bot(orchestrator: CaptainOrchestrator, config: dict):
    """Start the long-poll loop. Returns only when cancelled."""
    token = config.get("telegram_bot_token", "")
    owner_id_raw = config.get("telegram_owner_id", "")
    if not token or "TELEGRAM" in token.upper():
        log.info("Telegram bot disabled — telegram_bot_token not configured.")
        return

    try:
        from telegram import Update
        from telegram.ext import (
            Application, CommandHandler, MessageHandler, ContextTypes, filters,
        )
    except ImportError:
        log.warning("python-telegram-bot not installed — Telegram disabled.")
        return

    try:
        owner_id = int(owner_id_raw) if owner_id_raw else None
    except ValueError:
        owner_id = None

    if owner_id is None:
        log.error(
            "TELEGRAM_OWNER_ID is not set — the bot will IGNORE ALL messages. "
            "The agent holds live credentials, so an open bot is not an option. "
            "Set the TELEGRAM_OWNER_ID environment variable (send /start to "
            "@userinfobot on Telegram to find your numeric ID) and restart."
        )

    async def _authorized(update: Update) -> bool:
        # Fail closed: no owner configured means nobody is authorized.
        if owner_id is None:
            return False
        return update.effective_user and update.effective_user.id == owner_id

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            return
        await update.message.reply_text(
            "Captain Snow at your service. Send me anything — chat, search, email, plan."
        )

    async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not await _authorized(update):
            log.info("Ignored message from unauthorized user %s", update.effective_user.id)
            return
        text = (update.message.text or "").strip()
        if not text:
            return
        try:
            await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
            reply = await orchestrator.process_request(text)
        except Exception as e:
            log.exception("Orchestrator error")
            reply = f"Error: {e}"
        # Telegram caps messages at 4096 chars
        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i + 4000])

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Telegram bot started (owner_id=%s)", owner_id)

    # Manual lifecycle so we can run alongside FastAPI under asyncio.gather
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    try:
        # Block here forever; cancellation propagates from the parent task
        import asyncio
        while True:
            await asyncio.sleep(3600)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
