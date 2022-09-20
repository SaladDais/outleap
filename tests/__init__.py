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


class MockReqIDGenerator:
    """Predictable reqid generator for request reply tracking"""

    def __init__(self):
        self.ctr = 0

    def __call__(self, *args, **kwargs):
        self.ctr += 1
        return self.ctr


class BaseClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.protocol = MockLEAPProtocol()
        self.client = outleap.LEAPClient(self.protocol)
        self.client._gen_reqid = MockReqIDGenerator()

    async def asyncTearDown(self) -> None:
        self.client.disconnect()

    def _write_welcome(self):
        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "reply_pump",
                "data": {
                    "command": "cmd_pump",
                },
            }
        )

    def _write_reply(self, reqid: int, extra: Optional[Dict] = None):
        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "reply_pump",
                "data": {
                    **(extra or {}),
                    "reqid": reqid,
                },
            }
        )
