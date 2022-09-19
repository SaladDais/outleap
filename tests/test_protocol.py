from typing import *

import asyncio
import unittest

import outleap


class MockTransport(asyncio.Transport):
    def __init__(self):
        super().__init__()
        self.written_data = bytearray()

    def can_write_eof(self) -> bool:
        return True

    def is_closing(self) -> bool:
        return False

    def is_reading(self) -> bool:
        return False

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
        self.assertEqual(b"24:{\'pump\':\'foo\',\'data\':{}}", self.transport.written_data)
