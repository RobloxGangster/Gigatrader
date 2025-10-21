from __future__ import annotations

import asyncio
import json
from typing import Any

import websockets

from core.broker_config import AlpacaConfig


class StreamManager:
    """Maintain a lightweight Alpaca market data websocket connection."""

    def __init__(self, cfg: AlpacaConfig | None = None) -> None:
        self.cfg = cfg or AlpacaConfig()
        self._status = "offline"
        self._last_error: str | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._task: asyncio.Task[Any] | None = None
        self._reconnects = 0

    def status(self) -> dict[str, Any]:
        return {
            "state": self._status,
            "online": self._status == "online",
            "last_error": self._last_error,
            "reconnects": self._reconnects,
        }

    async def _run(self) -> None:
        backoff = 1
        while True:
            try:
                self._status = "connecting"
                async with websockets.connect(
                    self.cfg.data_ws_url,
                    ping_interval=20,
                    close_timeout=10,
                ) as ws:
                    self._ws = ws
                    await ws.send(
                        json.dumps(
                            {
                                "action": "auth",
                                "key": self.cfg.key_id,
                                "secret": self.cfg.secret_key,
                            }
                        )
                    )
                    await ws.send(
                        json.dumps(
                            {
                                "action": "subscribe",
                                "trades": [],
                                "quotes": [],
                                "bars": [],
                            }
                        )
                    )
                    self._status = "online"
                    backoff = 1
                    async for _ in ws:
                        pass
            except Exception as exc:  # pragma: no cover - network dependent
                self._last_error = str(exc)
                self._status = "offline"
                self._reconnects += 1
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass
            finally:
                self._ws = None

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        loop = loop or asyncio.get_event_loop()
        if not self._task or self._task.done():
            self._task = loop.create_task(self._run())

    def stop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Terminate the background websocket task if active."""

        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._status = "offline"

        try:
            loop = loop or asyncio.get_event_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            try:
                loop.create_task(self._close_ws())
            except RuntimeError:
                pass
        else:
            try:
                asyncio.run(self._close_ws())
            except RuntimeError:
                # Already inside a running loop without handle – fallback to sync close
                if self._ws is not None:
                    try:
                        self._ws.close()  # type: ignore[call-arg]
                    except Exception:
                        pass
                    finally:
                        self._ws = None

    async def reconnect(self) -> None:
        """Force a reconnection cycle with minimal disruption."""

        loop: asyncio.AbstractEventLoop | None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        self.stop(loop)
        await asyncio.sleep(0)
        if loop is None:
            loop = asyncio.get_event_loop()
        self.start(loop)
