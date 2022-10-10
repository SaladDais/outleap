from __future__ import annotations

import asyncio
import dataclasses
import pathlib
import posixpath
from typing import *

if TYPE_CHECKING:
    from .api_wrappers import LLWindowAPI


class UIPath(pathlib.PurePosixPath):
    __slots__ = []

    def __new__(cls, *args):
        if args == (".",) or args == ("/",):
            val = cls._from_parsed_parts("", "/", ["/"])
        elif len(args) == 1 and isinstance(args[0], str):
            val = cls._from_parsed_parts("", "/", ["/", *args[0].split("/")[1:]])
        else:
            val = super().__new__(cls, *args)
        return val

    @classmethod
    def for_floater(cls, floater_name: str) -> UIPath:
        return cls("/main_view/menu_stack/world_panel/Floater View") / floater_name

    def __str__(self) -> str:
        return "/" + "/".join(self._parts[1:])

    def __eq__(self, other):
        if isinstance(other, UIPath):
            return self._parts == other._parts
        if not other:
            return False
        return str(other) == str(self)

    @property
    def _cparts(self):
        # Cached casefolded parts, for hashing and comparison
        try:
            return self._cached_cparts
        except AttributeError:
            self._cached_cparts = tuple(self._parts)
            return self._cached_cparts

    def __hash__(self):
        return hash(self._cparts)

    # Polyfill for Python 3.8
    if not hasattr(pathlib.Path, "is_relative_to"):

        def is_relative_to(self, other: Union[str, UIPath]) -> bool:
            return str(self).startswith(str(other))


class UIRect(NamedTuple):
    bottom: int
    left: int
    right: int
    top: int


@dataclasses.dataclass
class UIElementInfo:
    available: bool
    class_name: str
    enabled: int
    enabled_chain: int
    rect: UIRect
    value: Any
    visible: int
    visible_chain: int

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


class UIElementTree(Mapping[UIPath, "UIElement"]):
    def __init__(self, window_api: LLWindowAPI):
        self._window_api: LLWindowAPI = window_api
        self._elem_info: Dict[UIPath, Optional[UIElementInfo]] = {}
        super().__init__()

    def __getitem__(self, key: Union[str, UIPath]) -> UIElement:
        if isinstance(key, str):
            key = UIPath(key)
        if key not in self._elem_info:
            raise KeyError(f"No element at {key}")
        return UIElement(key, self)

    def __len__(self) -> int:
        return len(self._elem_info)

    def __iter__(self) -> Iterator[UIPath]:
        return iter(self._elem_info)

    @property
    def root_children(self) -> List[UIElement]:
        return self.get_child_elems(UIPath("/"))

    def get_info_by_path(self, path: UIPath) -> UIElementInfo:
        return self._elem_info[path]

    def get_child_elems(self, path: UIPath) -> List[UIElement]:
        elems = []
        for maybe_path in self._elem_info.keys():
            # Yield all direct children in the same tree
            if not maybe_path.is_relative_to(path):
                continue
            if maybe_path.parent != path:
                continue
            elems.append(UIElement(maybe_path, self))
        return elems

    async def refresh_subtree(self, under: Optional[UIPath] = None, refresh_info: bool = False):
        """
        Drop and refresh all info about elements under `path`

        If refresh_info is specified, fetch additional info about all elements
        found, otherwise just use existing info about the elements if available.
        """
        # Elements may have been dropped, get rid of all elements under this path.
        old_paths: Dict[UIPath, Optional[UIElementInfo]] = {}
        for key, val in list(self._elem_info.items()):
            if not under or key.is_relative_to(under):
                old_paths[key] = self._elem_info[key]
                del self._elem_info[key]

        new_paths = await self._window_api.get_paths(under=under)

        for path in new_paths:
            # Fill map with either the old data or "None". Presence of "None"
            # distinguishes paths which don't exist within the tree from ones
            # which do exist, but for which we have no data.
            self._elem_info[path] = old_paths.get(path)

        if refresh_info:
            await self.fetch_info_for_paths(new_paths)

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
                elem_info = UIElementInfo(
                    available=info["available"],
                    class_name=info["class"],
                    enabled=info["enabled"],
                    enabled_chain=info["enabled_chain"],
                    rect=UIRect(**info["rect"]),
                    value=info.get("value"),
                    visible=info["visible"],
                    visible_chain=info["visible_chain"],
                )

            self._elem_info[UIPath(path)] = elem_info

    async def refresh(self, refresh_info: bool = False):
        await self.refresh_subtree(under=None, refresh_info=refresh_info)


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
    def have_info(self) -> bool:
        try:
            return self._tree.get_info_by_path(self.path) is not None
        except KeyError:
            return False

    @property
    def is_detached(self) -> bool:
        try:
            self._tree.get_info_by_path(self.path)
            return False
        except KeyError:
            return True

    @property
    def parent(self) -> Optional[UIElement]:
        if self.path.parent == self.path:
            return None
        return self._tree[self.path]

    def to_dict(self):
        return {
            "path": self.path,
            **self.info.to_dict(),
        }

    @property
    def children(self) -> List[UIElement]:
        return self._tree.get_child_elems(self.path)

    available: bool = UIElementProperty()
    class_name: str = UIElementProperty()
    enabled: int = UIElementProperty()
    enabled_chain: int = UIElementProperty()
    rect: UIRect = UIElementProperty()
    value: Any = UIElementProperty()
    visible: int = UIElementProperty()
    visible_chain: int = UIElementProperty()

    def __eq__(self, other) -> bool:
        if not isinstance(other, UIElement):
            return False
        if other._tree != self._tree:
            return False
        return other.path == self.path

    async def refresh_subtree(self, refresh_info=False):
        await self._tree.refresh_subtree(self.path, refresh_info=refresh_info)

    async def refresh(self):
        await self._tree.fetch_info_for_paths([self.path])


UI_PATH_TYPE = Optional[Union[str, UIPath, UIElement]]


__all__ = [
    "UIPath",
    "UIRect",
    "UIElement",
    "UIElementTree",
    "UI_PATH_TYPE",
]
