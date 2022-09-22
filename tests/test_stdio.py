"""
Test that LEAP scripts handle STDIO operations correctly
"""

import asyncio
import sys
import unittest

import outleap

TEST_CODE = """
import asyncio

from outleap import LEAPClient, LLViewerControlAPI


class MockReqIDGenerator:
    def __init__(self):
        self.ctr = 0

    def __call__(self, *args, **kwargs):
        self.ctr += 1
        return self.ctr


async def amain():
    # Create a client speaking LEAP over stdin/stdout and connect it
    async with await LEAPClient.create_stdio_client() as client:
        # Use monotonically incrementing integer for reqids
        client._gen_reqid = MockReqIDGenerator()
        # Use our typed wrapper around the LLViewerControl LEAP API
        viewer_control_api = LLViewerControlAPI(client)
        # Ask for a config value and print it in the viewer logs
        await viewer_control_api.get("Global", "StatsPilotFile")

loop = asyncio.get_event_loop_policy().get_event_loop()
loop.run_until_complete(amain())
"""


class STDIOTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            TEST_CODE,
            stdout=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.protocol = outleap.LEAPProtocol(self.proc.stdout, self.proc.stdin)

    def _write_hello(self):
        self.protocol.write_message(
            "reply_pump",
            {
                "command": "cmd_pump",
            },
        )

    async def _assert_normal_exit(self):
        await asyncio.wait_for(self.proc.wait(), 2.0)
        # We want to know if any warnings about dangling tasks or such were printed
        self.assertEqual(b"", await self.proc.stderr.read())
        self.assertEqual(0, self.proc.returncode)

    async def test_connect_and_reply(self):
        self._write_hello()
        msg = await self.protocol.read_message()
        self.assertEqual("LLViewerControl", msg["pump"])
        self.protocol.write_message(
            "reply_pump",
            {
                "value": "whatever",
                "reqid": 1,
            },
        )
        await self._assert_normal_exit()

    async def asyncTearDown(self) -> None:
        if self.proc.returncode is None:
            self.proc.kill()
