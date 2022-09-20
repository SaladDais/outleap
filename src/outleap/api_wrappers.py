from __future__ import annotations

import abc
import pathlib
import posixpath
import uuid
from typing import *

if TYPE_CHECKING:
    from .client import LEAPClient


class LEAPAPIWrapper(abc.ABC):
    """Base class for classes wrapping specific LEAP APIs"""

    PUMP_NAME: Optional[str] = None

    def __init__(self, client: LEAPClient, pump_name: Optional[str] = None):
        super().__init__()
        self._client = client
        self._pump_name = pump_name or self.PUMP_NAME
        assert self._pump_name


class UIPath(pathlib.PurePosixPath):
    __slots__ = []

    @classmethod
    def for_floater(cls, floater_name: str) -> UIPath:
        return cls("/main_view/menu_stack/world_panel/Floater View") / floater_name

    def __str__(self) -> str:
        """Like the base __str__ except ".." and "." segments will be resolved."""
        return posixpath.normpath(super().__str__())


async def _data_unwrapper(data_fut: Awaitable[Dict], inner_elem: str) -> Any:
    """Unwraps part of the data future while allowing the request itself to remain synchronous"""
    # We want the request to be sent immediately, without requiring the request to be `await`ed first,
    # but that means that we have to return a `Coroutine` that will pull the value out of the dict
    # rather than directly returning the `Future`.
    return (await data_fut)[inner_elem]


UI_PATH_TYPE = Optional[Union[str, UIPath]]


class LLWindowAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLWindow"

    MASK_TYPE = Optional[Collection[str]]
    KEYCODE_TYPE = Optional[int]
    KEYSYM_TYPE = Optional[str]
    CHAR_TYPE = Optional[str]
    MOUSE_COORD_TYPE: Optional[int]

    def _convert_key_payload(
        self,
        /,
        *,
        keycode: KEYCODE_TYPE,
        keysym: KEYSYM_TYPE,
        char: CHAR_TYPE,
        mask: MASK_TYPE,
        path: UI_PATH_TYPE,
    ) -> Dict:
        if keycode is not None:
            payload = {"keycode": keycode}
        elif keysym is not None:
            payload = {"keysym": keysym}
        elif char is not None:
            payload = {"char": char}
        else:
            raise ValueError("Didn't have one of keycode, keysym or char")

        if path:
            payload["path"] = str(path)
        if mask:
            payload["mask"] = mask

        return payload

    def key_down(
        self,
        /,
        *,
        mask: MASK_TYPE = None,
        keycode: KEYCODE_TYPE = None,
        keysym: KEYSYM_TYPE = None,
        char: CHAR_TYPE = None,
        path: UI_PATH_TYPE = None,
    ) -> None:
        """Simulate a key being pressed down"""
        payload = self._convert_key_payload(keysym=keysym, keycode=keycode, char=char, mask=mask, path=path)
        self._client.void_command(self._pump_name, "keyDown", payload)

    def key_up(
        self,
        /,
        *,
        mask: MASK_TYPE = None,
        keycode: KEYCODE_TYPE = None,
        keysym: KEYSYM_TYPE = None,
        char: CHAR_TYPE = None,
        path: UI_PATH_TYPE = None,
    ) -> None:
        """Simulate a key being released"""
        payload = self._convert_key_payload(keysym=keysym, keycode=keycode, char=char, mask=mask, path=path)
        self._client.void_command(self._pump_name, "keyUp", payload)

    def key_press(
        self,
        /,
        *,
        mask: MASK_TYPE = None,
        keycode: KEYCODE_TYPE = None,
        keysym: KEYSYM_TYPE = None,
        char: CHAR_TYPE = None,
        path: UI_PATH_TYPE = None,
    ) -> None:
        """Simulate a key being pressed down and immediately released"""
        self.key_down(mask=mask, keycode=keycode, keysym=keysym, char=char, path=path)
        self.key_up(mask=mask, keycode=keycode, keysym=keysym, char=char, path=path)

    def text_input(self, text_input: str, path: UI_PATH_TYPE = None) -> None:
        """Simulate a user typing a string of text"""
        # TODO: Uhhhhh I can't see how the key* APIs could possibly handle i18n correctly,
        #  what with all the U8s. Maybe I'm just dumb?
        for char in text_input:
            self.key_press(char=char, path=path)

    async def get_paths(self, under: UI_PATH_TYPE = "") -> Dict:
        """Get all UI paths under the root, or under a path if specified"""
        return await self._client.command(self._pump_name, "getPaths", {"under": str(under)})

    async def get_info(self, path: UI_PATH_TYPE) -> Dict:
        """Get info about an element specified by path"""
        return await self._client.command(self._pump_name, "getInfo", {"path": str(path)})

    def _build_mouse_payload(
        self,
        /,
        *,
        x: MOUSE_COORD_TYPE,
        y: MOUSE_COORD_TYPE,
        path: UI_PATH_TYPE,
        mask: MASK_TYPE,
        button: str = None,
    ) -> Dict:
        if path is not None:
            payload = {"path": str(path)}
        elif x is not None and y is not None:
            payload = {"x": x, "y": y}
        else:
            raise ValueError("Didn't have one of x + y or path")

        if mask:
            payload["mask"] = mask
        if button:
            payload["button"] = button

        return payload

    def mouse_down(
        self,
        /,
        *,
        x: MOUSE_COORD_TYPE = None,
        y: MOUSE_COORD_TYPE = None,
        path: UI_PATH_TYPE = None,
        mask: MASK_TYPE = None,
        button: str,
    ) -> Awaitable[Dict]:
        """Simulate a mouse down event occurring at a coordinate or UI element path"""
        payload = self._build_mouse_payload(x=x, y=y, path=path, mask=mask, button=button)
        return self._client.command(self._pump_name, "mouseDown", payload)

    def mouse_up(
        self,
        /,
        *,
        x: MOUSE_COORD_TYPE = None,
        y: MOUSE_COORD_TYPE = None,
        path: UI_PATH_TYPE = None,
        mask: MASK_TYPE = None,
        button: str,
    ) -> Awaitable[Dict]:
        """Simulate a mouse up event occurring at a coordinate or UI element path"""
        payload = self._build_mouse_payload(x=x, y=y, path=path, mask=mask, button=button)
        return self._client.command(self._pump_name, "mouseUp", payload)

    def mouse_click(
        self,
        /,
        *,
        x: MOUSE_COORD_TYPE = None,
        y: MOUSE_COORD_TYPE = None,
        path: UI_PATH_TYPE = None,
        mask: MASK_TYPE = None,
        button: str,
    ) -> Awaitable[Dict]:
        """Simulate a mouse down and immediately following mouse up event"""
        # We're going to ignore the mouseDown response, so use void_command instead.
        # Most side effects are actually executed on mouseUp.
        self._client.void_command(
            self._pump_name,
            "mouseDown",
            self._build_mouse_payload(x=x, y=y, path=path, mask=mask, button=button),
        )
        return self.mouse_up(x=x, y=y, path=path, mask=mask, button=button)

    def mouse_move(
        self, /, *, x: MOUSE_COORD_TYPE = None, y: MOUSE_COORD_TYPE = None, path: UI_PATH_TYPE = None
    ) -> Awaitable[Dict]:
        """Move the mouse to the coordinates or path specified"""
        payload = self._build_mouse_payload(x=x, y=y, path=path, mask=None)
        return self._client.command(self._pump_name, "mouseMove", payload)

    def mouse_scroll(self, clicks: int) -> None:
        """Act as if the scroll wheel has been moved `clicks` amount. May be negative"""
        self._client.command(self._pump_name, "mouseScroll", {"clicks": clicks})


class LLUIAPI(LEAPAPIWrapper):
    PUMP_NAME = "UI"

    def call(self, function: str, parameter: Any = None) -> None:
        """
        Invoke the `function` operation as if from a menu or button click, passing `parameter`

        Can call most things registered through `LLUICtrl::CommitCallbackRegistry`.
        """
        self._client.void_command(self._pump_name, "call", {"function": function, "parameter": parameter})

    def get_value(self, path: UI_PATH_TYPE) -> Awaitable[Any]:
        """For the UI control identified by `path`, return the current value in `value`"""
        resp_fut = self._client.command(self._pump_name, "getValue", {"path": str(path)})
        return _data_unwrapper(resp_fut, "value")


class LLCommandDispatcherAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLCommandDispatcher"

    def dispatch(
        self,
        cmd: str,
        /,
        *,
        params: Optional[Collection[str]] = None,
        query: Optional[Dict[str, str]] = None,
        trusted: bool = True,
    ) -> None:
        """Execute a command registered as an LLCommandHandler"""
        return self._client.void_command(
            self._pump_name,
            "dispatch",
            {
                "cmd": cmd,
                "params": params or [],
                "query": query or {},
                "trusted": trusted,
            },
        )

    def enumerate(self) -> Awaitable[Dict]:
        """Get map of registered LLCommandHandlers, containing name, key, and (e.g.) untrusted flag"""
        return self._client.command(self._pump_name, "enumerate")


class LLViewerControlAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLViewerControl"

    def get(self, group: str, key: str) -> Awaitable[Any]:
        """
        Get value of a Control (config) key

        `group` can be one of "CrashSettings", "Global", "PerAccount", "Warnings".
        """
        return self._client.command(self._pump_name, "get", {"key": key, "group": group})

    def vars(self, group: str) -> Awaitable[List[Dict]]:
        """Return a list of dicts of controls in `group`"""
        resp_fut = self._client.command(self._pump_name, "vars", {"group": group})
        return _data_unwrapper(resp_fut, "vars")

    def set(self, group: str, key: str, value: Any) -> None:
        """
        Set a configuration value

        TODO: error handling based on "error" field in resp?
        """
        self._client.void_command(self._pump_name, "set", {"key": key, "group": group, "value": value})


class LLViewerWindowAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLViewerWindow"

    def save_snapshot(
        self,
        filename: Union[str, pathlib.Path],
        /,
        *,
        width: Optional[int] = None,  # Uses current dimensions if not specified
        height: Optional[int] = None,
        show_hud: bool = True,
        show_ui: bool = True,
        rebuild: bool = False,  # I guess rebuild the UI or not before snapshot
        snap_type: str = "COLOR",  # may be "DEPTH" or "COLOR"
    ) -> Awaitable[bool]:
        """Save a snapshot to the local disk"""
        extras = {}
        if width is not None:
            extras["width"] = width
        if height is not None:
            extras["height"] = height
        fut = self._client.command(
            self._pump_name,
            "saveSnapshot",
            {
                "filename": str(filename),
                "showhud": show_hud,
                "showui": show_ui,
                "rebuild": rebuild,
                "type": snap_type,
                **extras,
            },
        )
        return _data_unwrapper(fut, "ok")

    def request_reshape(self, width: int, height: int) -> None:
        """Request the window be resized to the specified dimensions"""
        self._client.void_command(self._pump_name, "requestReshape", {"w": width, "h": height})


class LLAgentAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLAgent"

    def look_at(
        self,
        /,
        *,
        obj_uuid: Optional[uuid.UUID] = None,
        position: Optional[Sequence[float]] = None,
        lookat_type: int = 8,
    ):
        """Look at either a specific `obj_uuid` or the closest object to `position`"""
        payload = {"type": lookat_type}
        if obj_uuid:
            payload["obj_uuid"] = obj_uuid
        elif position:
            payload["position"] = list(position)
        else:
            raise ValueError("Must specify either obj_uuid or position")
        self._client.void_command(self._pump_name, "lookAt", payload)

    def get_auto_pilot(self) -> Awaitable[Dict]:
        """Get information about current state of the autopilot system"""
        return self._client.command(self._pump_name, "getAutoPilot", {})


__all__ = [
    "LLUIAPI",
    "LLAgentAPI",
    "LLWindowAPI",
    "LLViewerControlAPI",
    "LLViewerWindowAPI",
    "LLCommandDispatcherAPI",
    "UIPath",
    "LEAPAPIWrapper",
]
