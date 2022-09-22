#!/usr/bin/env python3
import asyncio
import sys

from outleap import LEAPClient, LLViewerControlAPI


async def amain():
    # Create a client speaking LEAP over stdin/stdout and connect it
    async with await LEAPClient.create_stdio_client() as client:
        # Use our typed wrapper around the LLViewerControl LEAP API
        viewer_control_api = LLViewerControlAPI(client)
        # Ask for a config value and print it in the viewer logs
        print(await viewer_control_api.get("Global", "StatsPilotFile"), file=sys.stderr)


def main():
    loop = asyncio.get_event_loop_policy().get_event_loop()
    loop.run_until_complete(amain())


if __name__ == "__main__":
    main()
