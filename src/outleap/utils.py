import asyncio
import os
import stat
import sys
import threading
import time
from typing import *


class HackySTDIOTransport(asyncio.Transport):
    def __init__(self):
        super().__init__()
        self.closed = False
        self.wrote_eof = False

    def can_write_eof(self) -> bool:
        return not self.closed and not self.wrote_eof

    def write_eof(self) -> None:
        assert self.can_write_eof()
        self.wrote_eof = True

    def is_closing(self) -> bool:
        return self.closed

    def is_reading(self) -> bool:
        return False

    def close(self) -> None:
        self.closed = True

    def write(self, data: Any) -> None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


class HackySTDIOProtocol(asyncio.Protocol):
    def __init__(self):
        super().__init__()

    def data_received(self, data: bytes) -> None:
        pass

    def eof_received(self) -> Union[bool, None]:
        return False

    def resume_writing(self) -> None:
        pass

    def pause_writing(self) -> None:
        pass

    async def _drain_helper(self):
        # no-op, we flush immediately.
        pass


def _stdin_feeder(
    transport: asyncio.Transport, reader: asyncio.StreamReader, loop: asyncio.AbstractEventLoop
):
    while not transport.is_closing():
        # Read up to 1024 bytes from stdin
        data = os.read(0, 1024)
        if not data:
            time.sleep(0.0001)
            continue
        loop.call_soon_threadsafe(reader.feed_data, data)
    reader.feed_eof()


async def _make_hacky_threaded_stdio_rw() -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    # NB: Windows has no non-blocking IO for stdin and stdout, so we have to resort to weird
    # hacks. Do blocking IO in a separate thread and feed it to a StreamReader so that we can
    # keep API symmetry across stdio & TCP LEAP code. Otherwise, we end up with an
    # un-cancellable Future like in the run_in_executor() case. We don't care if the thread
    # is still blocking trying to read when we exit, only one thing is trying to read from
    # stdin!
    # See https://stackoverflow.com/questions/31510190/aysncio-cannot-read-stdin-on-windows
    #
    # TODO: Currently we also use this if we're reading from a non-pipe file descriptor on POSIX
    #  platforms, but that's probably unnecessary.
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = HackySTDIOProtocol()
    transport = HackySTDIOTransport()
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)

    # Runs forever and dies with the process.
    t = threading.Thread(target=_stdin_feeder, args=(transport, reader, loop), daemon=True)
    t.daemon = True
    t.start()
    return reader, writer


def _is_unix_pipe(fileno: int) -> bool:
    mode = os.fstat(fileno).st_mode
    return stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode) or stat.S_ISCHR(mode)


async def connect_stdin_stdout() -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """
    Get a StreamReader and StreamWriter for stdin and stdout, respectively
    """
    # Windows (and probably cygwin) need special logic for non-blocking use of STDIO.
    need_stdin_hack = any(sys.platform.startswith(x) for x in ("cygwin", "win32"))
    if not need_stdin_hack:
        # We also need it if stdin isn't actually a pipe, the pipe will fail to connect!
        if not _is_unix_pipe(sys.stdin.fileno()) or not _is_unix_pipe(sys.stdout.fileno()):
            need_stdin_hack = True
    if need_stdin_hack:
        return await _make_hacky_threaded_stdio_rw()
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
