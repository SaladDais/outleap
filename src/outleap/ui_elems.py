from __future__ import annotations

import asyncio
import dataclasses
import weakref
from typing import *

if TYPE_CHECKING:
    from .api_wrappers import LLWindowAPI


class UIPath:
    __slots__ = ["_parts", "__weakref__"]
    # UIPaths are immutable, so we can maintain a cache of instances based on
    # the parts that make up the path.
    _INSTANCES: Dict[Tuple[str, ...], UIPath] = weakref.WeakValueDictionary()

    def __new__(cls, *args):
        if len(args) == 1:
            if isinstance(args[0], str):
                args = args[0].split("/")
                # "." means "/" in LEAP
                if tuple(args) == (".",):
                    args = ()
                else:
                    # Ignore empty segments
                    args = tuple([x for x in args if x])
            elif isinstance(args[0], UIPath):
                return args[0]
            else:
                args = tuple(args)
        else:
            args = tuple(args)

        # Check if we have a cached UIPath instance for these args first
        val = cls._INSTANCES.get(args)
        if val is not None:
            return val
        val = super().__new__(cls)
        val._parts = args
        cls._INSTANCES[args] = val
        return val

    @classmethod
    def for_floater(cls, floater_name: str) -> UIPath:
        return cls("/main_view/menu_stack/world_panel/Floater View") / floater_name

    def __str__(self) -> str:
        return "/" + "/".join(self._parts)

    def __repr__(self):
        return f"{self.__class__.__name__}({self!s})"

    def __eq__(self, other):
        if isinstance(other, UIPath):
            return self is other
        elif isinstance(other, str):
            return UIPath(other) == self
        return NotImplemented

    def __hash__(self):
        return hash(self._parts)

    @property
    def parent(self) -> UIPath:
        return UIPath(*self._parts[:-1])

    @property
    def stem(self) -> str:
        if self._parts:
            return self._parts[-1]
        return ""

    def __truediv__(self, other: Union[str, UIPath]):
        if not isinstance(other, (UIPath, str)):
            return NotImplemented
        if isinstance(other, str):
            other = UIPath(other)
        return UIPath(*self._parts, *other._parts)

    def __rtruediv__(self, other: Union[str, UIPath]):
        if not isinstance(other, (UIPath, str)):
            return NotImplemented
        if isinstance(other, str):
            other = UIPath(other)
        return UIPath(*other._parts, *self._parts)

    def is_relative_to(self, other: Union[str, UIPath]) -> bool:
        # 10x faster than pathlib's `is_relative_to()`.
        if isinstance(other, str):
            other = UIPath(other)
        other_len = len(other._parts)
        self_len = len(self._parts)
        # self should be a strict extension of other
        return self_len >= other_len and self._parts[:other_len] == other._parts


class UIRect(NamedTuple):
    bottom: int
    left: int
    right: int
    top: int

    def __mul__(self, factor: float) -> UIRect:
        return UIRect(
            *map(round, (self.bottom * factor, self.left * factor, self.right * factor, self.top * factor))
        )


@dataclasses.dataclass
class UIElementInfo:
    available: bool
    class_name: str
    enabled: bool
    enabled_chain: bool
    rect: UIRect
    value: Any
    visible: bool
    visible_chain: bool

    @classmethod
    def from_dict(cls, info: Dict) -> UIElementInfo:
        return cls(
            available=info["available"],
            class_name=info["class"],
            # These sometimes arrive as ints
            enabled=bool(info["enabled"]),
            enabled_chain=bool(info["enabled_chain"]),
            rect=UIRect(**info["rect"]),
            value=info.get("value"),
            visible=bool(info["visible"]),
            visible_chain=bool(info["visible_chain"]),
        )

    def to_dict(self):
        return {
            "available": self.available,
            "class": self.class_name,
            "enabled": self.enabled,
            "enabled_chain": self.enabled_chain,
            "rect": self.rect._asdict(),
            "value": self.value,
            "visible": self.visible,
            "visible_chain": self.visible_chain,
        }


@dataclasses.dataclass
class UIElementNode:
    """An element and its descendants, as returned by `LLWindowAPI.get_subtree()`"""

    path: UIPath
    info: Optional[UIElementInfo]
    children: Dict[UIPath, UIElementNode]

    @classmethod
    def from_dict(cls, node: Dict) -> UIElementNode:
        elem_node = cls(
            path=UIPath(node["path"]),
            info=UIElementInfo.from_dict(node) if "class" in node else None,
            children={},
        )
        # Leaf nodes have an undefined "children" rather than an empty array
        if (raw_children := node.get("children")) is not None:
            for raw_child in raw_children:
                elem_node.add_child(cls.from_dict(raw_child))
        return elem_node

    def add_child(self, child: UIElementNode):
        """Add a child, merging it into any existing child with the same path"""
        if (existing := self.children.get(child.path)) is not None:
            # Sibling views can share a name. The first one's info wins.
            for grandchild in child.children.values():
                existing.add_child(grandchild)
        else:
            self.children[child.path] = child

    def walk(self) -> Iterator[UIElementNode]:
        """Yield this node and all its descendants, depth-first"""
        yield self
        for child in self.children.values():
            yield from child.walk()


_T = TypeVar("T")


class UIElementProperty(Generic[_T]):
    __slots__ = ("name", "owner")

    def __init__(self):
        super().__init__()

    def __set_name__(self, owner, name: str):
        self.name = name

    def __get__(self, _obj: UIElement, owner: Optional[Type] = None) -> _T:
        # Reach into the UIElementTree for info related to the element our owner wraps.
        # Try to access the parameter related to this. This will intentionally fail if
        # the UIElement info aren't complete.
        return getattr(_obj.info, self.name)


class UIElement:
    """Wrapper around a tree and a path to access that path in the tree"""

    def __init__(self, path: UIPath, element_tree: UIElementTree):
        self.path = path
        self._tree = element_tree

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self):
        return f"{self.__class__.__name__}({str(self)!r})"

    @property
    def info(self) -> Optional[UIElementInfo]:
        return self._tree.get_info_by_path(self.path)

    @property
    def is_detached(self) -> bool:
        """Whether this element is still a valid node in its parent tree"""
        try:
            self._tree.get_info_by_path(self.path)
            return False
        except KeyError:
            return True

    @property
    def parent(self) -> Optional[UIElement]:
        parent = self.path.parent
        if parent == self.path:
            return None
        return self._tree[parent]

    @property
    def ancestors(self) -> Sequence[UIElement]:
        ancestors = []
        elem = self
        while elem := elem.parent:
            ancestors.append(elem)
        return ancestors

    def to_dict(self):
        info = self.info
        return {
            "path": self.path,
            **(info.to_dict() if info else {}),
        }

    @property
    def children(self) -> List[UIElement]:
        return self._tree.get_child_elems(self.path)

    available: bool = UIElementProperty()
    """Visible and may be interacted with"""
    class_name: str = UIElementProperty()
    """C++ class name of the element"""
    enabled: bool = UIElementProperty()
    """Whether this specific element is enabled"""
    enabled_chain: bool = UIElementProperty()
    """Whether everything in the element's ancestry is enabled"""
    rect: UIRect = UIElementProperty()
    """Extents of the element rect, not clipped to parent rects"""
    value: Any = UIElementProperty()
    """Logical value of the element, LLSD"""
    visible: bool = UIElementProperty()
    """Whether this specific element is set to be visible"""
    visible_chain: bool = UIElementProperty()
    """Whether everything in the element's ancestry is visible"""

    def __eq__(self, other) -> bool:
        if not isinstance(other, UIElement):
            return False
        if other._tree != self._tree:
            return False
        return other.path == self.path

    async def refresh_subtree(self):
        await self._tree.refresh_subtree(self.path)

    async def refresh(self):
        await self._tree.fetch_info_for_paths([self.path])


class UIElementTree(Mapping[UIPath, "UIElement"]):
    def __init__(self, window_api: LLWindowAPI):
        self._window_api: LLWindowAPI = window_api
        self._nodes: Dict[UIPath, UIElementNode] = {}
        super().__init__()

    def __getitem__(self, key: Union[str, UIPath]) -> UIElement:
        if isinstance(key, str):
            key = UIPath(key)
        if key not in self._nodes:
            raise KeyError(f"No element at {key}")
        return UIElement(key, self)

    def __contains__(self, item: Union[str, UIPath]) -> bool:
        if isinstance(item, str):
            item = UIPath(item)
        return item in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[UIPath]:
        return iter(self._nodes)

    @property
    def root_children(self) -> List[UIElement]:
        return self.get_child_elems(UIPath("/"))

    def get_info_by_path(self, path: UIPath) -> Optional[UIElementInfo]:
        return self._nodes[path].info

    def get_child_elems(self, path: UIPath) -> List[UIElement]:
        if (node := self._nodes.get(path)) is None:
            return []
        return [UIElement(child.path, self) for child in node.children.values()]

    async def refresh_subtree(self, under: Optional[UIPath] = None):
        """Drop and refresh all info about elements under `under`"""
        subtree = UIElementNode.from_dict(await self._window_api.get_subtree(under=under))

        if subtree.path == UIPath("/"):
            self._nodes = {node.path: node for node in subtree.walk()}
            return

        parent = self._get_or_create_node(subtree.path.parent)
        if (old := self._nodes.get(subtree.path)) is not None:
            for node in old.walk():
                del self._nodes[node.path]
        parent.children[subtree.path] = subtree

        for node in subtree.walk():
            self._nodes[node.path] = node

    def _get_or_create_node(self, path: UIPath) -> UIElementNode:
        """Get the node at `path`, creating empty nodes for it and any missing ancestors"""
        if (node := self._nodes.get(path)) is None:
            node = UIElementNode(path=path, info=None, children={})
            self._nodes[path] = node
            if path != UIPath("/"):
                self._get_or_create_node(path.parent).children[path] = node
        return node

    async def fetch_info_for_paths(self, paths: Collection[UIPath], allow_missing: bool = True):
        futs = [self._window_api.get_info(path) for path in paths]
        for path, info in zip(paths, await asyncio.gather(*futs)):
            if error := info.get("error"):
                if "request specified invalid" in error and allow_missing:
                    # Implicitly null elem_info for invalid paths. There are certain paths that
                    # are sort of valid but that the viewer refuses to respond to getInfo for.
                    # Don't remove them from the path tree, just say we don't have info.
                    elem_info = None
                else:
                    raise ValueError(error)
            else:
                elem_info = UIElementInfo.from_dict(info)

            if (node := self._nodes.get(UIPath(path))) is not None:
                node.info = elem_info

    async def refresh(self):
        await self.refresh_subtree(under=None)


UI_PATH_TYPE = Optional[Union[str, UIPath, UIElement]]


__all__ = [
    "UIPath",
    "UIRect",
    "UIElement",
    "UIElementInfo",
    "UIElementNode",
    "UIElementTree",
    "UI_PATH_TYPE",
]
