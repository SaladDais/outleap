from __future__ import annotations

import abc
import pathlib
import uuid
from typing import *

from .client import COMMAND_PUMP, PUMP_NAME_TYPE, CommandPumpToken, LEAPClient
from .ui_elems import UI_PATH_TYPE, UIPath


class LEAPAPIWrapper(abc.ABC):
    """Base class for classes wrapping specific LEAP APIs"""

    PUMP_NAME: Optional[PUMP_NAME_TYPE] = None

    def __init__(self, client: LEAPClient, pump_name: Optional[PUMP_NAME_TYPE] = None):
        super().__init__()
        self._client = client
        self._pump_name = pump_name or self.PUMP_NAME
        assert self._pump_name


async def _data_unwrapper(data_fut: Awaitable[Dict], inner_elem: str) -> Any:
    """Unwraps part of the data future while allowing the request itself to remain synchronous"""
    # We want the request to be sent immediately, without requiring the request to be `await`ed first,
    # but that means that we have to return a `Coroutine` that will pull the value out of the dict
    # rather than directly returning the `Future`.
    return (await data_fut)[inner_elem]


class CommandAPI(LEAPAPIWrapper):
    PUMP_NAME = COMMAND_PUMP

    def get_apis(self) -> Awaitable[dict]:
        """
        Get a list of all available LLEventAPI instances

        Returns a dict of API name -> API details
        """
        return self._client.command(self._pump_name, "getAPIs")

    def get_api(self, api_name: str) -> Awaitable[dict]:
        """Get details about a specific LLEventAPI instance, including supported methos"""
        return self._client.command(self._pump_name, "getAPI", {"api": api_name})

    def ping(self) -> Awaitable[None]:
        """Send a ping and await the pong"""
        return self._client.command(self._pump_name, "ping")

    def start_listening(self, listener_name: str, source_pump: PUMP_NAME_TYPE) -> Awaitable[bool]:
        """Start listening on a specific pump, using `listener_name`"""
        if isinstance(source_pump, CommandPumpToken):
            source_pump = self._client.cmd_pump
        fut = self._client.command(
            self._pump_name,
            "listen",
            {
                "listener": listener_name,
                "source": source_pump,
            },
        )
        return _data_unwrapper(fut, "status")

    def stop_listening(self, listener_name: str, source_pump: PUMP_NAME_TYPE) -> Awaitable[bool]:
        """Stop `listener_name` from listening on a specific pump"""
        if isinstance(source_pump, CommandPumpToken):
            source_pump = self._client.cmd_pump
        fut = self._client.command(
            self._pump_name,
            "stoplistening",
            {
                "listener": listener_name,
                "source": source_pump,
            },
        )
        return _data_unwrapper(fut, "status")


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
            payload: Dict = {"keycode": keycode}
        elif keysym is not None:
            payload: Dict = {"keysym": keysym}
        elif char is not None:
            payload: Dict = {"char": char}
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

    async def get_paths(self, under: Optional[UI_PATH_TYPE] = None) -> List[UIPath]:
        """Get all UI paths under the root, or under a path if specified"""
        resp = await self._client.command(self._pump_name, "getPaths", {"under": str(under or "")})
        if error := resp.get("error"):
            raise ValueError(error)
        return [UIPath(path) for path in resp.get("paths", [])]

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
            payload: Dict = {"path": str(path)}
        elif x is not None and y is not None:
            payload: Dict = {"x": x, "y": y}
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
        payload: Dict = {"type": lookat_type}
        if obj_uuid:
            payload["obj_uuid"] = obj_uuid
        elif position:
            payload["position"] = list(position)
        else:
            raise ValueError("Must specify either obj_uuid or position")
        self._client.void_command(self._pump_name, "lookAt", payload)

    def get_auto_pilot(self) -> Awaitable[Dict]:
        """Get information about the current state of the autopilot system"""
        return self._client.command(self._pump_name, "getAutoPilot", {})

    def get_agent_screen_pos(self, avatar_id: Optional[uuid.UUID] = None) -> Awaitable[Dict]:
        """Get where the specified agent is on the screen, uses current agent's ID if none provided"""
        payload = {}
        if avatar_id:
            payload["avatar_id"] = avatar_id
        return self._client.command(self._pump_name, "getAgentScreenPos", payload)

    def get_nearby_avatars(self, dist: Optional[float] = None) -> Awaitable[List[Dict]]:
        payload = {}
        if dist is not None:
            payload["dist"] = dist
        fut = self._client.command(self._pump_name, "getNearbyAvatarsList", payload)
        return _data_unwrapper(fut, "result")

    def get_nearby_objects(self, dist: Optional[float] = None) -> Awaitable[List[Dict]]:
        payload = {}
        if dist is not None:
            payload["dist"] = dist
        fut = self._client.command(self._pump_name, "getNearbyObjectsList", payload)
        return _data_unwrapper(fut, "result")

    def get_position(self) -> Awaitable[Dict]:
        """Get details about the agent's position"""
        return self._client.command(self._pump_name, "getPosition", {})

    def request_sit(
        self,
        obj_uuid: Optional[uuid.UUID] = None,
        position: Optional[Sequence[float]] = None,
    ) -> Awaitable:
        """Request to sit on obj_id, or object closest to position. Sits on ground if no args provided"""
        if position and obj_uuid is not None:
            raise ValueError("obj_uuid and position are mutually exclusive")

        params = {}
        if obj_uuid:
            params["obj_uuid"] = obj_uuid
        if position:
            params["position"] = list(position)
        return self._client.command(self._pump_name, "requestSit", params)

    def request_stand(self) -> None:
        self._client.void_command(self._pump_name, "requestStand", {})

    def request_teleport(
        self,
        region_name: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        z: Optional[int] = None,
        skip_confirmation: bool = True,
    ) -> None:
        """Request a teleport from the system, (x,y,z) are global if region_name unspecified"""
        have_coords = all(_ is not None for _ in (x, y, z))
        if not region_name and not have_coords:
            raise ValueError("region_name or (x,y,z) is required")

        params: Dict = {"skip_confirmation": skip_confirmation}
        if region_name:
            params["regionname"] = region_name
        if have_coords:
            params["x"] = x
            params["y"] = y
            params["z"] = z

        self._client.void_command(self._pump_name, "requestTeleport", params)

    def get_id(self) -> Awaitable[uuid.UUID]:
        """Get the current agent's ID"""
        return _data_unwrapper(self._client.command(self._pump_name, "getId", {}), "id")

    def get_groups(self) -> Awaitable[List[Dict]]:
        return _data_unwrapper(self._client.command(self._pump_name, "getGroups", {}), "groups")

    def play_animation(self, item_id: uuid.UUID, inworld: bool = True) -> Awaitable:
        """Play an animation by item id"""
        return self._client.command(
            self._pump_name, "playAnimation", {"item_id": item_id, "inworld": inworld}
        )

    def stop_animation(self, item_id: uuid.UUID) -> Awaitable:
        """Stop an animation by item id"""
        return self._client.command(self._pump_name, "stopAnimation", {"item_id": item_id})

    def get_animation_info(self, item_id: uuid.UUID) -> Awaitable[Dict]:
        """Get information about an animation by item id"""
        return _data_unwrapper(
            self._client.command(self._pump_name, "getAnimationInfo", {"item_id": item_id}), "anim_info"
        )

    def set_camera_params(self, params: Dict) -> None:
        """Set camera parameters using LSL-like semantics"""
        self._client.void_command(self._pump_name, "setCameraParams", params)

    def set_follow_cam_active(self, active: bool) -> None:
        self._client.void_command(self._pump_name, "setFollowCamActive", {"active": active})

    def remove_camera_params(self) -> None:
        self._client.void_command(self._pump_name, "removeCameraParams", {})

    def request_touch(
        self,
        obj_uuid: Optional[uuid.UUID] = None,
        position: Optional[Sequence[float]] = None,
        face: int = 0,
    ) -> None:
        if not obj_uuid and not position:
            raise ValueError("Must specify either obj_uuid or position")
        params: Dict = {"face": face}
        if obj_uuid:
            params["obj_uuid"] = obj_uuid
        if position:
            params["position"] = list(position)
        self._client.void_command(self._pump_name, "requestTouch", params)


class LLFloaterRegAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLFloaterReg"

    def get_build_map(self) -> Awaitable[Dict]:
        """Get a map of floater names and their XUI xml files"""
        return self._client.command(self._pump_name, "getBuildMap", {})

    def show_instance(self, name: str, key: Any = None, focus: bool = False) -> None:
        """
        Show an instance of a floater

        `key` may contain specific data to bootstrap creating the floater, for
        example an item ID.
        """
        self._client.void_command(
            self._pump_name,
            "showInstance",
            {
                "name": name,
                "key": key,
                "focus": focus,
            },
        )

    def hide_instance(self, name: str, key: Any = None) -> None:
        """Hide an instance of a floater"""
        self._client.void_command(
            self._pump_name,
            "hideInstance",
            {
                "name": name,
                "key": key,
            },
        )

    def toggle_instance(self, name: str, key: Any = None) -> None:
        """Toggle visibility of an instance of a floater"""
        self._client.void_command(
            self._pump_name,
            "toggleInstance",
            {
                "name": name,
                "key": key,
            },
        )

    def is_instance_visible(self, name: str, key: Any = None) -> Awaitable[bool]:
        """Return whether an instance was visible"""
        fut = self._client.command(
            self._pump_name,
            "instanceVisible",
            {
                "name": name,
                "key": key,
            },
        )
        return _data_unwrapper(fut, "visible")

    def click_button(self, name: str, button: str, key: Any = None) -> Awaitable[Dict]:
        """Click a button on an instance of a floater, potentially returning failure details"""
        return self._client.command(
            self._pump_name,
            "clickButton",
            {
                "name": name,
                "key": key,
                "button": button,
            },
        )


class LLURLDispatcherAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLUrlDispatcher"

    def dispatch(self, url: str, trusted: bool = True):
        """At startup time or on clicks in internal web browsers, teleport, open map, or run requested command."""
        self._client.void_command(self._pump_name, "dispatch", {"url": url, "trusted": trusted})

    def dispatch_right_click(self, url: str):
        """Dispatch ["url"] as if from a right-click on a hot link."""
        self._client.void_command(self._pump_name, "dispatchRightClick", {"url": url})

    def dispatch_from_text_editor(self, url: str):
        """Dispatch ["url"] as if from an edit field"""
        self._client.void_command(self._pump_name, "dispatchFromTextEditor", {"url": url})


class LLFloaterAboutAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLFloaterAbout"

    def get_info(self) -> Awaitable[dict]:
        """Request an LLSD::Map containing information used to populate About box"""
        return self._client.command(self._pump_name, "getInfo")


class LLGestureAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLGesture"

    def get_active_gestures(self) -> Awaitable[list]:
        """
        Return information about the agent's available gestures

        Returns a list of dicts with the following dict values for each entry:
        ["name"]: name of the gesture, may be empty
        ["trigger"]: trigger string used to invoke via user chat, may be empty
        ["playing"]: true or false indicating the playing state
        """
        fut = self._client.command(self._pump_name, "getActiveGestures")
        return _data_unwrapper(fut, "gestures")

    def is_gesture_playing(self, gesture_id: uuid.UUID) -> Awaitable[bool]:
        fut = self._client.command(self._pump_name, "isGesturePlaying", {"id": gesture_id})
        return _data_unwrapper(fut, "playing")

    def start_gesture(self, gesture_id: uuid):
        self._client.void_command(self._pump_name, "startGesture", {"id": gesture_id})

    def stop_gesture(self, gesture_id: uuid):
        self._client.void_command(self._pump_name, "stopGesture", {"id": gesture_id})


class GroupChatAPI(LEAPAPIWrapper):
    PUMP_NAME = "GroupChat"

    def start_im(self, group_id: uuid.UUID) -> Awaitable:
        """Start an IM session for the specified group"""
        return self._client.command(self._pump_name, "startGroupChat", {"group_id": group_id})

    def end_im(self, group_id: uuid.UUID):
        """End an IM session with the specified group"""
        return self._client.command(self._pump_name, "leaveGroupChat", {"group_id": group_id})

    def send_im(self, group_id: uuid.UUID, message: str) -> Awaitable:
        """Send an IM to the specified group"""
        return self._client.command(
            self._pump_name, "sendGroupIM", {"group_id": group_id, "message": message}
        )


class LLChatBarAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLChatBar"

    def send_chat(self, message: str, channel: int = 0, chat_type: str = "normal"):
        """
        Send chat to the simulator

        :param message: chat message text [required]
        :param channel: chat channel number [default = 0]
        :param chat_type: "whisper", "normal", "shout" [default = "normal"]
        """
        self._client.void_command(
            self._pump_name, "sendChat", {"message": message, "channel": channel, "chat_type": chat_type}
        )


class LLAppViewerAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLAppViewer"

    def request_quit(self):
        self._client.void_command(self._pump_name, "requestQuit")

    def force_quit(self):
        self._client.void_command(self._pump_name, "forceQuit")


class LLTeleportHandlerAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLTeleportHandler"

    def teleport(
        self,
        region_name: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        z: Optional[int] = None,
    ) -> None:
        have_coords = all(_ is not None for _ in (x, y, z))
        if not region_name and not have_coords:
            raise ValueError("region_name or (x,y,z) is required")

        params = {}
        if region_name:
            params["regionname"] = region_name
        if have_coords:
            params["x"] = x
            params["y"] = y
            params["z"] = z

        self._client.void_command(self._pump_name, "teleport", params)


class LLAppearanceAPI(LEAPAPIWrapper):
    PUMP_NAME = "LLAppearance"

    def wear_outfit(
        self,
        folder_id: Optional[uuid.UUID] = None,
        folder_name: Optional[str] = None,
        append: bool = False,
    ) -> Awaitable:
        params: Dict = {"append": append}
        if folder_id:
            params["folder_id"] = folder_id
        if folder_name:
            params["folder_name"] = folder_name
        return self._client.command(self._pump_name, "wearOutfit", params)

    def wear_items(self, item_ids: Sequence[uuid.UUID], replace: bool = False) -> None:
        self._client.void_command(
            self._pump_name, "wearItems", {"items_id": list(item_ids), "replace": replace}
        )

    def detach_items(self, item_ids: Sequence[uuid.UUID], replace: bool = False) -> None:
        self._client.void_command(
            self._pump_name, "detachItems", {"items_id": list(item_ids), "replace": replace}
        )

    def get_outfits_list(self) -> Awaitable[Dict[str, str]]:
        return _data_unwrapper(self._client.command(self._pump_name, "getOutfitsList", {}), "outfits")

    def get_outfit_items(self, outfit_id: uuid.UUID) -> Awaitable[Dict[str, dict]]:
        return _data_unwrapper(
            self._client.command(self._pump_name, "getOutfitItems", {"outfit_id": outfit_id}),
            "items",
        )


__all__ = [
    "CommandAPI",
    "LLUIAPI",
    "LLAgentAPI",
    "LLWindowAPI",
    "LLViewerControlAPI",
    "LLViewerWindowAPI",
    "LLCommandDispatcherAPI",
    "LLFloaterRegAPI",
    "LLURLDispatcherAPI",
    "LLFloaterAboutAPI",
    "LLGestureAPI",
    "GroupChatAPI",
    "LLChatBarAPI",
    "LLAppViewerAPI",
    "LLTeleportHandlerAPI",
    "LLAppearanceAPI",
    "LEAPAPIWrapper",
]
