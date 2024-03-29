import asyncio
import os
import sys

from . import BaseClientTest


class ProtocolTests(BaseClientTest):
    async def test_connect(self):
        self._write_welcome()
        await self.client.connect()
        self.assertTrue(self.client.connected)

    async def test_connect_process_id(self):
        self._write_welcome()
        await self.client.connect()
        self.assertEqual(1, self.client.viewer_pid)
        self.assertListEqual(["foo", "bar"], self.client.launch_args)

    async def test_connect_no_process_id(self):
        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "reply_pump",
                "data": {"command": "cmd_pump"},
            }
        )
        await self.client.connect()
        self.assertEqual(os.getppid(), self.client.viewer_pid)
        self.assertEqual(sys.argv[1:], self.client.launch_args)

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

    async def test_connect_bad_welcome(self):
        # Empty welcome message
        self.protocol.inbound_messages.put_nowait({})
        with self.assertRaises(KeyError):
            await self.client.connect()

    async def test_post(self):
        self._write_welcome()
        await self.client.connect()
        self.client.post("foopump", {"bar": 1}, expect_reply=False)  # noqa
        self.assertDictEqual({"pump": "foopump", "data": {"bar": 1}}, self.protocol.sent_messages[-1])

    async def test_post_bad_data(self):
        self._write_welcome()
        await self.client.connect()
        # Must post a dict if you expect a reply
        with self.assertRaises(ValueError):
            self.client.post("foopump", "foo", expect_reply=True)  # noqa

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
        expected_msg = {
            "pump": "foopump",
            "data": {"op": "baz", "bar": 1, "reply": "reply_pump", "reqid": 1},
        }
        self.assertDictEqual(expected_msg, last_message)

        # The reply hasn't come in yet, future should still be pending
        done, pending = await asyncio.wait([fut], timeout=0.01)
        self.assertEqual(set(), done)

        # Pretend a reply came in
        self._write_reply(1, {"foo": 1})
        # Work around weird Windows-only bug in wait_for() in Windows Python 3.12 :(
        # Seems that it doesn't return the result even though the future is marked done?
        await asyncio.sleep(0)
        self.assertEqual({"foo": 1}, await asyncio.wait_for(fut, timeout=0.05))

    async def test_disconnect_pending_command(self):
        self._write_welcome()
        async with self.client:
            fut = self.client.command("foo", "bar", {})

        with self.assertRaises(asyncio.CancelledError):
            await fut

    async def test_handle_bad_message(self):
        self._write_welcome()
        async with self.client:
            self.assertFalse(self.client.handle_message("foo"))

    async def test_handle_reply_not_dict(self):
        self._write_welcome()
        async with self.client:
            self.assertFalse(
                self.client.handle_message(
                    {
                        "pump": "reply_pump",
                        "data": "foo",
                    }
                )
            )

    async def test_handle_reply_no_reqid(self):
        self._write_welcome()
        async with self.client:
            self.assertFalse(
                self.client.handle_message(
                    {
                        "pump": "reply_pump",
                        "data": {},
                    }
                )
            )

    async def test_listen(self):
        self._write_welcome()
        await self.client.connect()
        listen_fut = self.client.listen("SomeState")
        # Pretend a reply came in allowing the listen
        self._write_reply(1)
        listener = await listen_fut

        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "SomeState",
                "data": "hi",
            }
        )

        msg = await listener.get()
        self.assertEqual("hi", msg)

        self.assertTrue(listener.empty())

        # Done, unregister the listen
        stop_listen_fut = self.client.stop_listening(listener)
        # Pretend a reply came in stopping the listen
        self._write_reply(2)
        await stop_listen_fut

    async def test_listen_shutdown(self):
        self._write_welcome()
        await self.client.connect()
        listen_fut = self.client.listen("SomeState")
        # Pretend a reply came in allowing the listen
        self._write_reply(1)
        listener = await listen_fut

        # Let the get() run until the yield
        listener_fut = asyncio.create_task(listener.get())
        done, pending = await asyncio.wait([listener_fut], timeout=0.0001)

        # Disconnect the client, triggering queue closure for all of the listeners
        self.client.disconnect()
        # The get() that was pending before the disconnect should be cancelled
        with self.assertRaises(asyncio.CancelledError):
            await list(pending)[0]
        # Any get()s done after that should return QueueEmpty
        with self.assertRaises(asyncio.QueueEmpty):
            await listener.get()

    async def test_listen_message_from_before_disconnect(self):
        self._write_welcome()
        await self.client.connect()
        listen_fut = self.client.listen("SomeState")
        # Pretend a reply came in allowing the listen
        self._write_reply(1)
        listener = await listen_fut

        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "SomeState",
                "data": "hi",
            }
        )
        await asyncio.sleep(0)
        self.client.disconnect()

        self.assertFalse(listener.empty())
        msg = await listener.get()
        self.assertEqual("hi", msg)
        self.assertTrue(listener.empty())

    async def test_listen_ctx_mgr(self):
        self._write_welcome()
        await self.client.connect()
        # Listener registration happening from within the contextmanager is annoying to mock,
        # so we just register a manual listener first.
        listen_fut = self.client.listen("SomeState")
        # Pretend a reply came in allowing the listen
        self._write_reply(1)
        first_listener = await listen_fut

        async with self.client.listen_scoped("SomeState") as listener:
            self.protocol.inbound_messages.put_nowait(
                {
                    "pump": "SomeState",
                    "data": "hi",
                }
            )
            msg = await listener.get()
            self.assertEqual("hi", msg)

        # Done, unregister the listen
        stop_listen_fut = self.client.stop_listening(first_listener)
        # Pretend a reply came in stopping the listen
        self._write_reply(2)
        await stop_listen_fut
