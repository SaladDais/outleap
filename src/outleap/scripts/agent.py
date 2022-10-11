"""
Stub for forwarding LEAP stdin/stdout to a LEAP receiver over TCP using netcat.

Really not much use to anyone but me until viewers correctly un-gate LEAP access :)
Hint: uncomment https://vcs.firestormviewer.org/phoenix-firestorm/files/cf85e854/indra/newview/llappviewer.cpp#L1398-1420

Usage: While an outleap TCP receiver is running
  ./firestorm --leap outleap-agent
"""
import asyncio
import multiprocessing

from outleap.utils import connect_stdin_stdout


async def _forward_stream(src_reader: asyncio.StreamReader, dst_writer: asyncio.StreamWriter):
    while not src_reader.at_eof() and not dst_writer.is_closing():
        dst_writer.write(await src_reader.read(0xFF00))
        await dst_writer.drain()


async def amain():
    serv_reader, serv_writer = await asyncio.open_connection("127.0.0.1", 9063, limit=10_000_000)
    stdio_reader, stdio_writer = await connect_stdin_stdout()

    try:
        agent_to_serv_fut = asyncio.create_task(_forward_stream(stdio_reader, serv_writer))
        serv_to_agent_fut = asyncio.create_task(_forward_stream(serv_reader, stdio_writer))
        await asyncio.gather(agent_to_serv_fut, serv_to_agent_fut)
    except asyncio.CancelledError:
        pass


def agent_main():
    loop = asyncio.get_event_loop_policy().get_event_loop()
    loop.run_until_complete(amain())


if __name__ == "__main__":
    multiprocessing.freeze_support()
    agent_main()
