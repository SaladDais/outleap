"""
Code related to the stdin/stdout -> TCP connectback bridge
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from typing import *

from .client import LEAPClient
from .protocol import LEAPProtocol


class LEAPBridgeServer:
    """LEAP Bridge TCP server to use with asyncio.start_server()"""

    def __init__(self, client_connected_cb: Optional[Callable[[LEAPClient]], Awaitable[Any]] = None):
        self.clients: weakref.WeakSet[LEAPClient] = weakref.WeakSet()
        self._client_connected_cb = client_connected_cb

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        client = LEAPClient(LEAPProtocol(reader, writer))
        logging.info("Accepting LEAP connection from %r" % (writer.get_extra_info("peername", None),))
        await client.connect()

        self.clients.add(client)
        if self._client_connected_cb:
            await self._client_connected_cb(client)


__all__ = [
    "LEAPBridgeServer",
]
