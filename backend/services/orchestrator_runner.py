from __future__ import annotations

import asyncio
import logging
from typing import Callable

from backend.routers.deps import get_orchestrator

log = logging.getLogger(__name__)


def run_trading_loop(stop_requested: Callable[[], bool]) -> None:
    """Run the orchestrator until the stop callback evaluates to True."""

    async def _main() -> None:
        orchestrator = get_orchestrator()
        started = False
        try:
            await orchestrator.start()
            started = True
            log.info("orchestrator background loop started")
            while not stop_requested():
                await asyncio.sleep(1.0)
        except Exception:  # pragma: no cover - runtime defensive guard
            log.exception("orchestrator background loop crashed")
            raise
        finally:
            try:
                await orchestrator.stop()
            except Exception:  # pragma: no cover - ensure stop errors surface
                log.exception("orchestrator background loop stop failed")
                if started:
                    raise
            else:
                log.info("orchestrator background loop stopped")

    asyncio.run(_main())


__all__ = ["run_trading_loop"]
