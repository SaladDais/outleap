import asyncio
import unittest
import unittest.mock
from typing import *

import outleap


class MockTransport(asyncio.Transport):
    def __init__(self):
        super().__init__()
        self.written_data = bytearray()
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
        self.written_data.extend(data)


class MockProtocol(asyncio.Protocol):
    def __init__(self):
        super().__init__()
        self.received_data = bytearray()

    def data_received(self, data: bytes) -> None:
        self.received_data.extend(data)

    def eof_received(self) -> Union[bool, None]:
        return False

    def resume_writing(self) -> None:
        pass

    def pause_writing(self) -> None:
        pass

    async def _drain_helper(self):
        pass


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.transport = MockTransport()
        self.protocol = MockProtocol()
        self.reader = asyncio.StreamReader()
        self.writer = asyncio.StreamWriter(self.transport, self.protocol, self.reader, self.loop)
        self.leap_protocol = outleap.LEAPProtocol(self.reader, self.writer)

    async def test_read(self):
        self.reader.feed_data(b"2:{}")
        self.assertEqual({}, await self.leap_protocol.read_message())

    async def test_write(self):
        self.leap_protocol.write_message("foo", {})
        self.assertEqual(b"24:{'pump':'foo','data':{}}", self.transport.written_data)

    async def test_read_non_dict(self):
        self.reader.feed_data(b"2:i1")
        with self.assertRaises(ValueError):
            await self.leap_protocol.read_message()

    async def test_read_too_long(self):
        payload = b"'" + (b"0" * 0xFFFFFF) + b"'"
        payload = str(len(payload)).encode("utf8") + b":" + payload
        self.reader.feed_data(payload)
        with unittest.mock.patch.object(self.leap_protocol, "PAYLOAD_LIMIT", 0xFFFFFF):
            with self.assertRaisesRegex(ValueError, "length"):
                await self.leap_protocol.read_message()

    async def test_close(self):
        self.assertFalse(self.leap_protocol.closed)
        self.leap_protocol.close()
        self.assertTrue(self.leap_protocol.closed)
