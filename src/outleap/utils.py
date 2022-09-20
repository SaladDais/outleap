import asyncio
import sys
from typing import *


async def connect_stdin_stdout() -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """
    Get a StreamReader and StreamWriter for stdin and stdout, respectively

    Unlikely to play nicely on Windows, it only has blocking IO on pipes!
    TODO: kick off a background pumping thread for windows pipes?
    """
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    w_transport, w_protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(w_transport, w_protocol, reader, loop)
    return reader, writer


__all__ = [
    "connect_stdin_stdout",
]
