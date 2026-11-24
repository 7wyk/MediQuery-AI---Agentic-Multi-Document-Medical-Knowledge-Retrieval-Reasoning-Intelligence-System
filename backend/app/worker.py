"""Standalone background worker entrypoint (e.g. a Render Background Worker).

Usage:  python -m app.worker
"""

from __future__ import annotations

import asyncio
import logging
import signal

from app.services.jobs import worker_loop
from app.services.observability import configure_logging, install_log_filter

logger = logging.getLogger(__name__)


async def main() -> None:
    configure_logging()
    install_log_filter()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    logger.info("Starting MediQuery AI document worker")
    await worker_loop(stop_event)
    logger.info("Worker stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
