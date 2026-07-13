"""
Long-running production entry point: runs the FastAPI web UI and the
Telegram bot together under a single asyncio loop, sharing one
CaptainOrchestrator instance.
"""

import asyncio
import logging
import os
import signal

import uvicorn

from .web import app as fastapi_app, orchestrator, config
from .telegram_bot import run_telegram_bot

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
# httpx logs every request URL at INFO — for Telegram that URL contains the
# bot token, which must not end up in container logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("captainsnow.serve")


async def _run_web():
    port = int(os.environ.get("PORT", 8000))
    cfg = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(cfg)
    log.info("FastAPI serving on http://0.0.0.0:%d", port)
    await server.serve()


async def _amain():
    # Run both forever; if either raises, the other is cancelled and the
    # process exits — the container runtime (Docker HEALTHCHECK) restarts us.
    web_task = asyncio.create_task(_run_web(), name="web")
    bot_task = asyncio.create_task(run_telegram_bot(orchestrator, config), name="telegram")

    # Graceful shutdown on SIGTERM (sent by the container runtime on redeploy)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows dev — signal handlers not supported in selector loop
            pass

    done, pending = await asyncio.wait(
        {web_task, bot_task, asyncio.create_task(stop.wait(), name="stop")},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()
    for t in pending:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
    log.info("Captain Snow shutting down.")


def main():
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
