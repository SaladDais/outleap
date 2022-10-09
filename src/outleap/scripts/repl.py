"""
Interactive REPL that handles connect-back connections from outleap-agent
"""
import asyncio
import logging
import multiprocessing
import pprint
import sys
import uuid

try:
    import ptpython
except ImportError:
    print("ptpython must be installed to use the REPL", file=sys.stderr)
    raise

import outleap


class REPLServer:
    def __init__(self):
        self._repl_running = False

    async def client_connected(self, client: outleap.LEAPClient):
        if self._repl_running:
            logging.error("Client already connected, ignoring incoming connection")
            return

        self._repl_running = True

        new_globals = {
            **globals(),
            "pprint": pprint,
            "UUID": uuid.UUID,
        }
        # Simulate `from outleap import *` in the REPL's global environment
        for name in outleap.__all__:
            new_globals[name] = getattr(outleap, name)

        try:
            await ptpython.repl.embed(  # noqa: the type signature lies
                globals=new_globals,
                locals={"client": client},
                return_asyncio_coroutine=True,
                patch_stdout=False,
            )
        finally:
            self._repl_running = False


def repl_main():
    logging.basicConfig()
    loop = asyncio.get_event_loop_policy().get_event_loop()
    repl_server = REPLServer()
    server = outleap.LEAPBridgeServer(repl_server.client_connected)
    coro = asyncio.start_server(server.handle_connection, "127.0.0.1", 9063)
    loop.run_until_complete(coro)
    print("REPL listening for inbound outleap-agent connections!", file=sys.stderr)
    loop.run_forever()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    repl_main()
