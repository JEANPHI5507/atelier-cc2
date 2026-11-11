"""The camera for the workshop's pages: one picture at a time, always the newest.

The printer's MJPEG (about 20 pictures/s, 5 Mbit/s) relayed as is reaches a phone on 4G or over
Tailscale late, then cut: pycentauri's relay drops raw byte chunks for a slow viewer, which breaks the
JPEGs in the middle, and an <img> on a broken or dropped stream just freezes on its last picture.
Here one reader cuts the stream into whole pictures and keeps the last one; each page asks for the next
picture once the previous one is shown. A slow connection gets fewer pictures, never late or broken
ones, and a page knows at once when one does not come.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
MAX_BUF = 4 << 20        # a stream with no picture end in 4 MB is not a camera: start over
IDLE_STOP_S = 30.0       # nobody looking for this long: stop reading
WAIT_S = 3.0             # how long a page's request waits for a new picture


class CameraFeed:
    def __init__(self, broadcaster: Any) -> None:
        self.cam = broadcaster
        self.frame: bytes | None = None
        self.seq = 0
        self.at = 0.0                      # when the last picture came
        self.asked = 0.0                   # when a page last asked
        self.new = asyncio.Condition()
        self.task: asyncio.Task | None = None

    def _start(self) -> None:
        self.asked = time.time()
        if self.task is None or self.task.done():
            self.task = asyncio.get_running_loop().create_task(self._read(), name="atelier-camera")

    async def _read(self) -> None:
        while time.time() - self.asked < IDLE_STOP_S:
            try:
                _, chunks = await self.cam.subscribe()
                buf = b""
                async for chunk in chunks:
                    buf += chunk
                    while (a := buf.find(SOI)) >= 0 and (b := buf.find(EOI, a + 2)) >= 0:
                        await self._publish(buf[a:b + 2])
                        buf = buf[b + 2:]
                    if len(buf) > MAX_BUF:
                        buf = b""
                    if time.time() - self.asked > IDLE_STOP_S:
                        with contextlib.suppress(Exception):
                            await chunks.aclose()   # leave the shared relay: the printer keeps one connection
                        return
            except asyncio.CancelledError:
                raise
            except Exception as e:      # camera away (printer off, LAN mode off): try again shortly
                log.info("caméra: %s", e)
            await asyncio.sleep(2)

    async def _publish(self, jpeg: bytes) -> None:
        async with self.new:
            self.frame, self.seq, self.at = jpeg, self.seq + 1, time.time()
            self.new.notify_all()

    async def next(self, after: int) -> tuple[int, bytes] | None:
        """A picture newer than ``after`` (waits up to WAIT_S for one), else the last one if still fresh."""
        self._start()
        async with self.new:
            with contextlib.suppress(asyncio.TimeoutError, TimeoutError):
                await asyncio.wait_for(self.new.wait_for(lambda: self.seq > after), WAIT_S)
            if self.frame is None or time.time() - self.at > 10:
                return None
            return self.seq, self.frame
