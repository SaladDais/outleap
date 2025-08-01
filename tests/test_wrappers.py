import asyncio

import outleap

from . import BaseClientTest


class TestWrappers(BaseClientTest):
    async def test_mouse_click(self):
        self._write_welcome()
        await self.client.connect()
        llwindow_api = outleap.LLWindowAPI(self.client)

        async def _fake_acks():
            for i in range(1, 3):
                await asyncio.sleep(0.05)
                self.protocol.inbound_messages.put_nowait(
                    {
                        "pump": "reply_pump",
                        "data": {
                            "handled": True,
                            "reqid": i,
                        },
                    }
                )

        # Make sure the request looks like what we'd expect
        fut = llwindow_api.mouse_click(x=0, y=1, mask=["CTL"], button="LEFT")
        await asyncio.gather(fut, _fake_acks())
        self.assertDictEqual(
            {
                "pump": "LLWindow",
                "data": {
                    "x": 0,
                    "y": 1,
                    "mask": ["CTL"],
                    "button": "LEFT",
                    "op": "mouseUp",
                    "reply": "reply_pump",
                    "reqid": 2,
                },
            },
            self.protocol.sent_messages[-1],
        )
        self.assertEqual(2, len(self.protocol.sent_messages[-1]))

    async def test_key_press(self):
        self._write_welcome()
        await self.client.connect()
        llwindow_api = outleap.LLWindowAPI(self.client)

        # Make sure the request looks like what we'd expect
        llwindow_api.key_press(char="f", mask=["CTL"])
        self.assertDictEqual(
            {"pump": "LLWindow", "data": {"char": "f", "mask": ["CTL"], "op": "keyUp"}},
            self.protocol.sent_messages[-1],
        )
        self.assertEqual(2, len(self.protocol.sent_messages[-1]))

    async def test_uipath_key_down(self):
        self._write_welcome()
        await self.client.connect()

        llwindow_api = outleap.LLWindowAPI(self.client)
        llwindow_api.key_down(char="f", path=outleap.UIPath.for_floater("foo") / "bar_elem")
        self.assertDictEqual(
            {
                "pump": "LLWindow",
                "data": {
                    "char": "f",
                    "path": "/main_view/menu_stack/world_panel/Floater View/foo/bar_elem",
                    "op": "keyDown",
                },
            },
            self.protocol.sent_messages[-1],
        )

    async def test_command_wrapper(self):
        self._write_welcome()
        await self.client.connect()

        llwindow_api = outleap.CommandAPI(self.client)
        fut = llwindow_api.get_api("foo")
        self.assertDictEqual(
            {
                "pump": self.client.cmd_pump,
                "data": {
                    "api": "foo",
                    "op": "getAPI",
                    "reply": "reply_pump",
                    "reqid": 1,
                },
            },
            self.protocol.sent_messages[-1],
        )
        self.protocol.inbound_messages.put_nowait(
            {
                "pump": "reply_pump",
                "data": {
                    "whatever": "foo",
                    "reqid": 1,
                },
            }
        )
        self.assertEqual("foo", (await fut)["whatever"])
