"""
binance_ws.py — Binance combined WebSocket runner with auto-reconnect.

DATA_PIPELINE_PLAN.md §7.2 and §7.3:
- Connects to wss://fstream.binance.com/stream?streams=...
- Combined stream for markPrice@1s and forceOrder across all symbols.
- Handles unexpected disconnects with exponential backoff.
- Deliberate reconnect before 24-hour Binance server cut.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Coroutine, List, Optional
import websockets

from app.config import get_settings

logger = logging.getLogger(__name__)


class BinanceWebSocketRunner:
    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        on_message_callback: Optional[Callable[[dict], Coroutine]] = None,
    ):
        settings = get_settings()
        self.symbols = symbols or settings.symbol_list
        self.ws_base = settings.binance_futures_ws.rstrip("/")
        self.callback = on_message_callback
        self._running = False

    def build_stream_url(self) -> str:
        """Create combined stream URL for markPrice and forceOrder."""
        streams = []
        for s in self.symbols:
            low = s.lower()
            streams.append(f"{low}@markPrice@1s")
            streams.append(f"{low}@forceOrder")
        stream_path = "/".join(streams)
        return f"{self.ws_base}/stream?streams={stream_path}"

    async def start(self):
        """Continuously run WebSocket with auto-reconnect and backoff."""
        self._running = True
        url = self.build_stream_url()
        backoff = 1.0

        logger.info("Starting Binance WebSocket runner for %d symbols", len(self.symbols))

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    logger.info("Connected to Binance WebSocket stream")
                    backoff = 1.0  # reset backoff upon successful connection

                    # Binance disconnects after 24h; reconnect proactively after 23h
                    reconnect_task = asyncio.create_task(asyncio.sleep(23 * 3600))

                    while self._running:
                        recv_task = asyncio.create_task(ws.recv())
                        done, pending = await asyncio.wait(
                            [recv_task, reconnect_task],
                            return_when=asyncio.FIRST_COMPLETED,
                        )

                        if reconnect_task in done:
                            logger.info("Proactive 23h WebSocket reconnect...")
                            recv_task.cancel()
                            break

                        msg = recv_task.result()
                        data = json.loads(msg)
                        if self.callback:
                            await self.callback(data)

            except (websockets.ConnectionClosed, asyncio.TimeoutError, Exception) as exc:
                if not self._running:
                    break
                logger.warning("WebSocket disconnected: %s. Reconnecting in %.1fs...", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    def stop(self):
        self._running = False

