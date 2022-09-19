import asyncio
import unittest
from typing import *

import outleap


class MockLEAPProtocol(outleap.AbstractLEAPProtocol):
    def __init__(self):
        self.closed = False
        self.sent_messages = []
        self.inbound_messages = asyncio.Queue()

    def close(self) -> None:
        self.closed = True

    def write_message(self, pump: str, data: Any) -> None:
        self.sent_messages.append({"pump": pump, "data": data})

    async def read_message(self) -> Dict:
        msg = await self.inbound_messages.get()
        self.inbound_messages.task_done()
        return msg


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.protocol = MockLEAPProtocol()
        self.client = outleap.LEAPClient(self.protocol)

    def _write_welcome(self):
        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "reply_pump",
                "data": {
                    "command": "cmd_pump",
                },
            }
        )

    async def test_connect(self):
        self._write_welcome()
        await self.client.connect()
        self.assertTrue(self.client.connected)

    async def test_disconnect(self):
        self._write_welcome()
        await self.client.connect()
        self.client.disconnect()
        self.assertFalse(self.client.connected)

    async def test_scoped_connect(self):
        self._write_welcome()
        self.assertFalse(self.client.connected)
        async with self.client:
            self.assertTrue(self.client.connected)

        self.assertFalse(self.client.connected)

    async def test_post(self):
        self._write_welcome()
        await self.client.connect()
        self.client.post("foopump", {"bar": 1}, expect_reply=False)  # noqa
        self.assertDictEqual({"pump": "foopump", "data": {"bar": 1}}, self.protocol.sent_messages[-1])

    async def test_void_command(self):
        self._write_welcome()
        await self.client.connect()
        self.client.void_command("foopump", "baz", {"bar": 1})
        self.assertDictEqual(
            {"pump": "foopump", "data": {"op": "baz", "bar": 1}}, self.protocol.sent_messages[-1]
        )

    async def test_command(self):
        self._write_welcome()
        await self.client.connect()
        fut = self.client.command("foopump", "baz", {"bar": 1})
        # Verify that the side effect of sending the message happens _before_ we await.
        last_message = self.protocol.sent_messages[-1]
        expected_reqid = last_message["data"]["reqid"]
        expected_msg = {
            "pump": "foopump",
            "data": {"op": "baz", "bar": 1, "reply": "reply_pump", "reqid": expected_reqid},
        }
        self.assertDictEqual(expected_msg, last_message)

        # The reply hasn't come in yet, future should still be pending
        done, pending = await asyncio.wait([fut], timeout=0.01)
        self.assertEqual(set(), done)

        # Pretend a reply came in
        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "reply_pump",
                "data": {
                    "reqid": expected_reqid,
                    "foo": 1,
                },
            }
        )
        self.assertEqual({"foo": 1}, await asyncio.wait_for(fut, timeout=0.01))
