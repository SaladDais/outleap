# outleap

[![codecov](https://codecov.io/gh/SaladDais/outleap/branch/master/graph/badge.svg?token=FWRKJNNJSZ)](https://codecov.io/gh/SaladDais/outleap)

A Python library using asyncio to control a Second Life viewer over the LEAP protocol.

See <https://bitbucket.org/lindenlab/leap/src/main/> for more details on LEAP.

## Installing

`pip install outleap`, or `pip install -e .` to install from source.

## Usage

Look in the "[examples](examples)" directory.

You can run a LEAP script with `your_viewer --leap some_script.py` if you have the executable bit set.

```python
import asyncio
import sys

from outleap import LEAPClient, LEAPProtocol, LLViewerControlAPI, connect_stdin_stdout


async def amain():
    # Create a client speaking LEAP over stdin/stdout and connect it
    reader, writer = await connect_stdin_stdout()
    async with LEAPClient(LEAPProtocol(reader, writer)) as client:
        # Use our typed wrapper around the LLViewerControl LEAP API
        viewer_control_api = LLViewerControlAPI(client)
        # Ask for a config value and print it in the viewer logs
        print(await viewer_control_api.get("Global", "StatsPilotFile"), file=sys.stderr)


loop = asyncio.get_event_loop_policy().get_event_loop()
loop.run_until_complete(amain())
```

## What viewers does LEAP even work in?

Due to the fact that LEAP has only historically been used internally for testing, or for
integration with the official viewer's updater, many viewers have disabled LEAP
both intentionally or accidentally.

The code in the upstream viewer also appears to refuse to launch LEAP scripts if the updater
isn't present, which I don't entirely understand. I can't compile it to check.

### Does it work in Firestorm?

No, the code to launch LEAP scripts is [commented out](https://vcs.firestormviewer.org/phoenix-firestorm/files/cf85e854/indra/newview/llappviewer.cpp#L1398-1420).
If you do your own build with those lines uncommented it'll work fine.

### Does it work in Alchemy?

[Probably not, and definitely not on Linux](https://git.alchemyviewer.org/alchemy/alchemy-next/-/blob/4f3b0d10e2f9db30e9e16bedbc4602b6d7bb5dda/indra/newview/llappviewer.cpp#L1183-1281).
Alchemy does the same SL updater presence checks as upstream before attempting to launch LEAP scripts, which
I imagine wouldn't succeed. Haven't tried.

### Does it work in LL's official viewer?

Yeah, probably.

### Does it work in `<other viewer>`?

No, probably not.

## Credits

The project scaffolding is based on code from https://github.com/MatthieuDartiailh/bytecode
