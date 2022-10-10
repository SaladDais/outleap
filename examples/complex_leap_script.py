#!/usr/bin/env python
"""
Simple example uses of the various LEAP APIs.

May be run either directly by the viewer, or through a TCP connect-back using --tcp.
"""

import asyncio
import logging
import pprint
import sys
from typing import *

from outleap import (
    LLUIAPI,
    LEAPBridgeServer,
    LEAPClient,
    LLCommandDispatcherAPI,
    LLFloaterRegAPI,
    LLViewerControlAPI,
    LLWindowAPI,
    UIPath,
)


async def client_connected(client: LEAPClient):
    printer = pprint.PrettyPrinter(stream=sys.stderr)
    # Kick off a request to get ops for each API supported by the viewer
    # Won't wait for a response from the viewer between each send
    api_futs: Dict[Awaitable, str] = {}
    for api_name in (await client.sys_command("getAPIs")).keys():
        api_fut = client.sys_command("getAPI", {"api": api_name})
        api_futs[api_fut] = api_name

    # Wait for all of our getAPI commands to complete in parallel
    for fut in (await asyncio.wait(api_futs.keys()))[0]:
        # Print out which API this future even relates to
        print("=" * 5, api_futs[fut], "=" * 5, file=sys.stderr)
        # List supported ops for this api
        printer.pprint(await fut)

    # Subscribe to StartupState events within this scope
    async with client.listen_scoped("StartupState") as listener:
        # Get a single StartupState event then continue
        printer.pprint(await listener.get())

    # More manual version of above that gives you a Queue you can pass around
    # A None gets posted to the mainloop every time the viewer restarts the main loop,
    # so we can rely on _something_ being published to this.
    mainloop_listener = await client.listen("mainloop")
    try:
        printer.pprint(await mainloop_listener.get())
    finally:
        await client.stop_listening(mainloop_listener)

    # A simple command with a reply
    # Let's not use the fancy API wrappers for now.
    printer.pprint(await client.command("LLFloaterReg", "getBuildMap"))

    # A simple command that has no reply, or has a reply we don't care about.
    client.void_command("LLFloaterReg", "showInstance", {"name": "preferences"})

    # Some commands must be executed against the dynamically assigned command
    # pump that's specific to our LEAP listener. `sys_command()` is the same as
    # `command()` except it internally addresses whatever the system command pump is.
    await client.sys_command("ping")

    # Print out all the commands supported by LLCommandDispatcher
    cmd_dispatcher_api = LLCommandDispatcherAPI(client)
    printer.pprint(await cmd_dispatcher_api.enumerate())

    # Spawn the test textbox floater, we can use the nice API wrapper for that.
    floater_reg_api = LLFloaterRegAPI(client)
    floater_reg_api.show_instance("test_textbox")

    # LEAP allows addressing UI elements by "path". We expose that through a pathlib-like interface
    # to allow composing UI element paths.
    textbox_path = UIPath.for_floater("floater_test_textbox") / "long_text_editor"
    # Click the "long_text_editor" in the test textbox floater.
    window_api = LLWindowAPI(client)
    await window_api.mouse_click(button="LEFT", path=textbox_path)

    # Clear out the textbox, note that this does _not_ work when path is specified!
    # TODO: clearing a textbox isn't so nice. CTL+A doesn't work as expected even without a path,
    #  it leaves a capital "A" in the text editor. We get rid of it by doing backspace right after.
    window_api.key_press(mask=["CTL"], keysym="a")
    window_api.key_press(keysym="Backsp")

    # Type some text
    window_api.text_input("Also I can type in here pretty good.")

    # Print out the value of the textbox we just typed in
    ui_api = LLUIAPI(client)
    printer.pprint(await ui_api.get_value(textbox_path))

    # But you don't need to explicitly give input focus like above, you can send keypresses
    # directly to a path.
    monospace_path = UIPath.for_floater("floater_test_textbox") / "monospace_text_editor"
    window_api.text_input("I typed in here by path.", path=monospace_path)

    # We can also access the viewer config to reason about viewer state.
    viewer_control_api = LLViewerControlAPI(client)
    printer.pprint(await viewer_control_api.get("Global", "StatsPilotFile"))
    # Print the first ten vars in the "Global" group
    printer.pprint((await viewer_control_api.vars("Global"))[:10])

    # Done, bye!
    client.disconnect()


def receiver_main():
    logging.basicConfig(level=logging.INFO)
    loop = asyncio.get_event_loop_policy().get_event_loop()

    args = sys.argv[1:]
    if args and args[0] == "--tcp":
        # In this mode viewers connect to the script over TCP,
        # and multiple viewers may be controlled by the same script at once.
        print("Ok, running in TCP daemon mode, will wait for connect-backs!", file=sys.stderr)
        server = LEAPBridgeServer(client_connected)
        coro = asyncio.start_server(server.handle_connection, "127.0.0.1", 9063)
        loop.run_until_complete(coro)
        loop.run_forever()
    else:
        # In this mode viewers directly execute the script via their --leap argument.
        # Only one viewer may be controlled.
        print(
            "Running in direct LEAP execution mode.\n"
            "If you're seeing this anywhere other than the viewer logs, "
            "you probably messed up, the viewer should be executing this!\n"
            "Try adding a '--tcp' argument!",
            file=sys.stderr,
        )

        async def _wrapper():
            async with await LEAPClient.create_stdio_client() as client:
                await client_connected(client)

        loop.run_until_complete(_wrapper())


if __name__ == "__main__":
    receiver_main()
