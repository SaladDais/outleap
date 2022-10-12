import asyncio
import pathlib
import unittest
from typing import *

import outleap

from . import MockLEAPProtocol

THIS_DIR = pathlib.Path(__file__).parent.absolute()
UI_PATHS: List[str] = []
with open(THIS_DIR / "ui_paths.txt", "r") as f:
    for path in f:
        UI_PATHS.append(path.strip())


class MockLEAPClient(outleap.LEAPClient):
    def command(self, pump: str, op: str, data: Optional[Dict] = None) -> Optional[asyncio.Future]:
        fut = asyncio.Future()
        if pump == "LLWindow":
            if op == "getPaths":
                fut.set_result({"paths": UI_PATHS[:] * 20})
            else:
                assert False
        else:
            assert False
        return fut


class TestUIElems(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.client = MockLEAPClient(MockLEAPProtocol())
        self.window_api = outleap.LLWindowAPI(self.client)
        self.tree = outleap.UIElementTree(self.window_api)

    async def test_load_paths(self):
        await self.tree.refresh()
        root_child_paths = [x.path for x in self.tree.root_children]
        self.assertListEqual(["/main_view", "/console"], root_child_paths)

    async def test_walk_children(self):
        await self.tree.refresh()

        children_map = {}

        def _walk_children(node: outleap.UIElement, parent: Optional[outleap.UIPath]):
            children_map[parent] = node
            for child in node.children:
                _walk_children(child, node.path)

        for node in self.tree.root_children:
            _walk_children(node, None)

    async def test_get_parent(self):
        await self.tree.refresh()
        self.assertEqual("/", self.tree["/main_view"].parent.path)
        self.assertIsNone(self.tree["/"].parent)
