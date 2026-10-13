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


def _build_subtree(under: str) -> Dict:
    nodes: Dict[UIPath, Dict] = {}
    for path_str in UI_PATHS:
        path = UIPath(path_str)
        # Like the real viewer, the root's path is "" and leaves have undefined children
        node = {"path": "" if path == UIPath("/") else str(path), "children": None, **ELEM_INFO}
        nodes.setdefault(path, node)
    for path_str in UI_PATHS:
        path = UIPath(path_str)
        if path.parent != path:
            parent = nodes[path.parent]
            parent["children"] = (parent["children"] or []) + [nodes[path]]
    return nodes[UIPath(under or "/")]


class MockLEAPClient(outleap.LEAPClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests: List[Tuple[str, Optional[Dict]]] = []
        self.subtree: Optional[Dict] = None

    def command(self, pump: str, op: str, data: Optional[Dict] = None) -> Optional[asyncio.Future]:
        self.requests.append((op, data))
        fut = asyncio.Future()
        if pump == "LLWindow":
            if op == "getSubtree":
                fut.set_result(self.subtree or _build_subtree(data["under"]))
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


ELEM_INFO = {
    "available": True,
    "class": "LLButton",
    "enabled": 1,
    "enabled_chain": 0,
    "rect": {"bottom": 0, "left": 1, "right": 2, "top": 3},
    "value": "hi",
    "visible": 1,
    "visible_chain": 1,
}


class TestUIElementNode(unittest.TestCase):
    def test_from_dict(self):
        node = outleap.UIElementNode.from_dict(
            {
                "path": "/main_view/foo",
                **ELEM_INFO,
                "children": [
                    {"path": "/main_view/foo/bar", **ELEM_INFO, "children": []},
                ],
            }
        )
        self.assertEqual(UIPath("/main_view/foo"), node.path)
        self.assertEqual("LLButton", node.info.class_name)
        self.assertIs(True, node.info.enabled)
        self.assertIs(False, node.info.enabled_chain)
        self.assertEqual(outleap.UIRect(bottom=0, left=1, right=2, top=3), node.info.rect)
        self.assertEqual([UIPath("/main_view/foo/bar")], list(node.children))

    def test_from_dict_no_info(self):
        node = outleap.UIElementNode.from_dict({"path": "/", "children": []})
        self.assertEqual(UIPath("/"), node.path)
        self.assertIsNone(node.info)
        self.assertEqual({}, node.children)

    def test_from_dict_undefined_children(self):
        # The viewer sends leaves' "children" as undefined, and the root's path as ""
        node = outleap.UIElementNode.from_dict({"path": "", **ELEM_INFO, "children": None})
        self.assertEqual(UIPath("/"), node.path)
        self.assertEqual({}, node.children)

    def test_walk(self):
        node = outleap.UIElementNode.from_dict(
            {
                "path": "/",
                "children": [
                    {"path": "/a", "children": [{"path": "/a/b", "children": []}]},
                    {"path": "/c", "children": []},
                ],
            }
        )
        self.assertEqual(["/", "/a", "/a/b", "/c"], [str(x.path) for x in node.walk()])

    def test_from_dict_merges_same_path_siblings(self):
        node = outleap.UIElementNode.from_dict(
            {
                "path": "/",
                "children": [
                    {
                        "path": "/a",
                        **ELEM_INFO,
                        "value": "first",
                        "children": [{"path": "/a/b", "children": None}],
                    },
                    {
                        "path": "/a",
                        **ELEM_INFO,
                        "value": "second",
                        "children": [
                            {"path": "/a/b", "children": [{"path": "/a/b/c", "children": None}]},
                            {"path": "/a/d", "children": None},
                        ],
                    },
                ],
            }
        )
        self.assertEqual(["/", "/a", "/a/b", "/a/b/c", "/a/d"], [str(x.path) for x in node.walk()])
        self.assertEqual("first", node.children[UIPath("/a")].info.value)


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

    async def test_load_info(self):
        await self.tree.refresh()
        self.assertEqual("LLButton", self.tree["/main_view"].info.class_name)
        self.assertEqual("LLButton", self.tree["/"].info.class_name)

    async def test_no_dupe_children(self):
        await self.tree.refresh()
        for elem in self.tree.values():
            child_paths = [x.path for x in elem.children]
            self.assertEqual(len(set(child_paths)), len(child_paths))

    async def test_refresh_subtree(self):
        await self.tree.refresh()
        num_elems = len(self.tree)
        self.client.requests.clear()

        await self.tree["/main_view"].refresh_subtree()
        self.assertEqual([("getSubtree", {"under": "/main_view"})], self.client.requests)
        self.assertEqual(num_elems, len(self.tree))
        self.assertIn("/console", self.tree)
        self.assertEqual(["/main_view", "/console"], [x.path for x in self.tree.root_children])

    async def test_same_path_siblings_merged(self):
        def node(path, children=None, **kwargs):
            return {"path": path, **ELEM_INFO, **kwargs, "children": children}

        self.client.subtree = node(
            "",
            [
                node("/menu", [node("/menu/a")], value="first"),
                node("/menu", [node("/menu/b"), node("/menu/a")], value="second"),
            ],
        )
        await self.tree.refresh()
        self.assertEqual(["/menu"], [x.path for x in self.tree.root_children])
        self.assertEqual(["/menu/a", "/menu/b"], [x.path for x in self.tree["/menu"].children])
        self.assertEqual("first", self.tree["/menu"].info.value)
