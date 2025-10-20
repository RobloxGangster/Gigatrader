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

    def status(self) -> dict[str, Any]:
        return {"status": self._status, "last_error": self._last_error}

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
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        loop = loop or asyncio.get_event_loop()
        if not self._task or self._task.done():
            self._task = loop.create_task(self._run())
