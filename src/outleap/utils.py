import asyncio
import io
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


_READER_BUFFER_LIMIT = 10_000_000


def _stdin_feeder(
    transport: asyncio.Transport, reader: asyncio.StreamReader, loop: asyncio.AbstractEventLoop
):
    while not transport.is_closing():
        data = os.read(0, _READER_BUFFER_LIMIT)
        if not data:
            time.sleep(0.0000001)
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
    reader = asyncio.StreamReader(limit=_READER_BUFFER_LIMIT)
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


# Modern Linux allows pipe sizes to be increased up to 1MB without special perms by default
# https://man7.org/linux/man-pages/man2/fcntl.2.html
_PIPE_BUFFER_SIZE = 1_000_000


def _patch_stdio_buffering():
    """
    Improve LEAP performance by giving stdin and stdout larger buffers

    Due to how the viewer's LEAP bridge is implemented, it will yield to the main loop
    if the child's stdin pipe fills. The default pipe size on Linux is about 8k. This
    leads to the LEAP write yielding for 0.05~s every time it writes an 8k chunk, which
    obviously leads to very bad perf for larger payloads:

    https://bitbucket.org/lindenlab/viewer/src/f83289d3a7e80bebe47f696f96aee1b7e64d1d69/indra/llcommon/llprocess.cpp#lines-228:235

    By increasing the size of the stdin / stdout pipes, we reduce the number of times
    the viewer must yield to the main loop while sending us the payload, reducing
    apparent function call time by 10x for larger payloads.

    Only works on Linux on Python 3.10+ due to relying on pipe implementation details
    """
    try:
        import fcntl
    except ImportError:
        # Will probably happen on OS X
        return
    try:
        # https://man7.org/linux/man-pages/man2/fcntl.2.html
        set_pipe_size = getattr(fcntl, "F_SETPIPE_SZ")
    except AttributeError:
        # Will probably happen on Python before 3.10
        return
    # Might fail, don't care. Best efforts only.
    pipes = [sys.stdin, sys.stdout]
    for pipe in pipes:
        try:
            if not _is_unix_pipe(pipe.fileno()):
                continue
            fcntl.fcntl(pipe.fileno(), set_pipe_size, _PIPE_BUFFER_SIZE)
        except (OSError, io.UnsupportedOperation):
            pass


async def connect_stdin_stdout() -> Tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """
    Get a StreamReader and StreamWriter for stdin and stdout, respectively
    """
    _patch_stdio_buffering()
    # Windows (and probably cygwin) need special logic for non-blocking use of STDIO.
    need_stdin_hack = any(sys.platform.startswith(x) for x in ("cygwin", "win32"))
    if not need_stdin_hack:
        # We also need it if stdin isn't actually a pipe, the pipe will fail to connect!
        if not _is_unix_pipe(sys.stdin.fileno()) or not _is_unix_pipe(sys.stdout.fileno()):
            need_stdin_hack = True
    if need_stdin_hack:
        return await _make_hacky_threaded_stdio_rw()
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader(limit=_READER_BUFFER_LIMIT)
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    w_transport, w_protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(w_transport, w_protocol, reader, loop)
    return reader, writer


__all__ = [
    "connect_stdin_stdout",
]
