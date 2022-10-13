import asyncio
import pathlib
import unittest
from typing import *

import outleap
from outleap import UIPath

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


class TestUIPaths(unittest.TestCase):
    def test_relative_to(self):
        self.assertTrue(UIPath("/foo/bar").is_relative_to(UIPath("/foo")))
        self.assertTrue(UIPath("/foo/bar").is_relative_to(UIPath("/")))
        self.assertTrue(UIPath("/").is_relative_to(UIPath("/")))
        self.assertFalse(UIPath("/").is_relative_to(UIPath("/foo")))

    def test_stem(self):
        self.assertEqual("foo", UIPath("/bar/foo").stem)
        self.assertEqual("", UIPath("/").stem)

    def test_normalize_dot(self):
        self.assertEqual("/", str(UIPath(".")))

    def test_div(self):
        self.assertEqual("/foo/bar/baz", str(UIPath("/foo/bar") / "baz"))
        self.assertEqual("/foo/bar/baz", str("/foo/bar" / UIPath("baz")))

    def test_eq(self):
        self.assertEqual(UIPath("/foo/bar"), UIPath("/foo/bar"))
        self.assertNotEqual(UIPath("/foo/bar"), UIPath("/foo"))
        self.assertEqual(UIPath("/foo/bar"), "/foo/bar")

    def test_get_parent(self):
        self.assertEqual(UIPath("/"), UIPath("/foo").parent)
        self.assertEqual(UIPath("/foo"), UIPath("/foo/bar").parent)


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
