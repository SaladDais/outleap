import abc
import asyncio
from typing import *

import llsd


class AbstractLEAPProtocol(abc.ABC):
    """Interface for a class representing communication with a LEAP peer"""

    closed: bool

    @abc.abstractmethod
    def close(self) -> None:
        pass

    @abc.abstractmethod
    def write_message(self, pump: str, data: Any) -> None:
        pass

    @abc.abstractmethod
    async def read_message(self) -> Dict:
        pass


class LEAPProtocol(AbstractLEAPProtocol):
    """Wrapper for communication with a LEAP peer over an asyncio reader/writer pair"""

    PAYLOAD_LIMIT = 0x0FFFFFFF

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader = reader
        self._writer = writer
        self._parser = llsd.serde_notation.LLSDNotationParser()
        self._formatter = llsd.serde_notation.LLSDNotationFormatter()
        self._drain_task = None

    @property
    def closed(self) -> bool:
        return self._writer.is_closing() or self._reader.at_eof()

    def close(self):
        if not self._writer.is_closing():
            self._writer.write_eof()
            self._writer.close()

    def write_message(self, pump: str, data: Any) -> None:
        assert not self._writer.is_closing()
        ser = self._formatter.format({"pump": pump, "data": data})
        payload = bytearray(str(len(ser)).encode("utf8"))
        payload.extend(b":")
        payload.extend(ser)
        self._writer.write(payload)
        # We're in sync context, we need to schedule draining the socket, which is async.
        # If a drain is already scheduled then we don't need to reschedule.
        if not self._drain_task:
            self._drain_task = asyncio.create_task(self._drain_soon())

    async def _drain_soon(self) -> None:
        self._drain_task = None
        await self._writer.drain()

    async def read_message(self) -> Dict:
        assert not self._reader.at_eof()

        # Length is everything up until the first colon we see, stripping the colon off.
        length = int((await self._reader.readuntil(b":"))[:-1].decode("utf8"))
        if length > self.PAYLOAD_LIMIT:
            raise ValueError(f"Unreasonable LEAP payload length of {length}")
        # Everything after the colon is LLSD
        parsed = self._parser.parse(await self._reader.readexactly(length))
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected LEAP message to be a dict, got {parsed!r}")
        return parsed


__all__ = [
    "AbstractLEAPProtocol",
    "LEAPProtocol",
]
