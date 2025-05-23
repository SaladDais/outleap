from __future__ import annotations

import asyncio
import collections
import dataclasses
import enum
import logging
import os
import sys
import uuid
from types import TracebackType
from typing import *

from .protocol import AbstractLEAPProtocol, LEAPProtocol
from .utils import connect_stdin_stdout


class CommandPumpToken:
    pass


COMMAND_PUMP = CommandPumpToken()

PUMP_NAME_TYPE = Union[CommandPumpToken, str]


class LEAPClient:
    """Client for script -> viewer communication over the LEAP protocol"""

    def __init__(self, protocol: AbstractLEAPProtocol):
        self._protocol = protocol
        # Pump used for receiving replies
        self._reply_pump: Optional[str] = None
        # Pump used for sending leap meta-commands to the viewer (getAPIs, etc.)
        self.cmd_pump: Optional[str] = None
        # Process ID of the viewer connecting to us
        self.viewer_pid: Optional[int] = None
        # Arguments the script the client belongs to was launched with
        # This is necessary to distinguish between LEAP scripts launched with
        # the --leap arguments and those launched as puppetry plugins.
        self.launch_args: Optional[List[str]] = None
        # Map of req id -> future held by requester to send responses to
        self._reply_futs: Dict[uuid.UUID, asyncio.Future] = {}
        self._pump_listeners: Dict[str, ListenerDetails] = collections.defaultdict(ListenerDetails)
        self._connection_status = ConnectionStatus.READY
        self._msg_pump_task: Optional[asyncio.Task] = None
        self.shutdown_event = asyncio.Event()

    @classmethod
    async def create_stdio_client(cls) -> LEAPClient:
        """Return an already-connected LEAPClient that talks over stdin/out"""
        reader, writer = await connect_stdin_stdout()
        client = cls(LEAPProtocol(reader, writer))
        await client.connect()
        return client

    async def __aenter__(self) -> LEAPClient:
        if not self.connected:
            await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Disconnect if we weren't already disconnected.
        self.disconnect()

    @property
    def connected(self) -> bool:
        return self._connection_status == ConnectionStatus.CONNECTED

    async def connect(self) -> None:
        """Receive the "hello" message from the viewer and start the message pump"""
        assert self._connection_status == ConnectionStatus.READY
        self._connection_status = ConnectionStatus.CONNECTING

        try:
            welcome_message = await self._protocol.read_message()
            self._reply_pump = welcome_message["pump"]
            self.cmd_pump = welcome_message["data"]["command"]
            self.viewer_pid = welcome_message["data"].get("process_id")
            self.launch_args = welcome_message["data"].get("args")
            if self.viewer_pid is None:
                # handshake didn't include the process ID, assume our own parent
                # process ID is the viewer's process ID.
                self.viewer_pid = os.getppid()
            if self.launch_args is None:
                self.launch_args = sys.argv[1:]

            self._connection_status = ConnectionStatus.CONNECTED
            self._start_message_pump()
        except:
            self.disconnect()
            raise

    def _start_message_pump(self) -> None:
        """Read and handle inbound messages in a background task"""

        async def _pump_messages_forever():
            try:
                while not self._protocol.closed:
                    self.handle_message(await self._protocol.read_message())
            except asyncio.IncompleteReadError:
                pass
            except ConnectionResetError:
                # This can happen on Windows rather than `IncompleteReadError`
                pass
            finally:
                self.disconnect()

        # Should naturally stop on its own when disconnect is called by virtue of
        # the incomplete read.
        self._msg_pump_task = asyncio.create_task(_pump_messages_forever())

    def disconnect(self) -> None:
        """Close the connection and clean up any pending request futures"""
        if self.connected:
            logging.info("closing LEAP connection")
        if not self.shutdown_event.is_set():
            self.shutdown_event.set()
        self._connection_status = ConnectionStatus.DISCONNECTED
        self._protocol.close()
        if self._msg_pump_task:
            self._msg_pump_task.cancel()
            self._msg_pump_task = None

        # Clean up any pending request futures
        for fut in list(self._reply_futs.values()):
            if not fut.done():
                fut.cancel()
        self._reply_futs.clear()
        # Tell anything listening on these queues that the queues are now closed.
        for listener_details in self._pump_listeners.values():
            for listener in listener_details.listeners:
                listener.close_queue()
        self._pump_listeners.clear()

    def command(
        self, pump: PUMP_NAME_TYPE, op: str, data: Optional[Dict] = None, op_key: str = "op"
    ) -> Optional[asyncio.Future]:
        """Make a request to an internal LEAP method using the standard command form (op in data)"""
        data = data.copy() if data else {}
        data[op_key] = op
        return self.post(pump, data, expect_reply=True)

    def void_command(
        self, pump: PUMP_NAME_TYPE, op: str, data: Optional[Dict] = None, op_key: str = "op"
    ) -> None:
        """Like `command()`, but we don't expect a reply."""
        data = data.copy() if data else {}
        data[op_key] = op
        self.post(pump, data, expect_reply=False)

    def post(self, pump: PUMP_NAME_TYPE, data: Any, expect_reply: bool) -> Optional[asyncio.Future]:
        """
        Post an event to the other side's `pump`.

        Post the event is done synchronously, only waiting for the reply is done async.
        """
        assert self.connected
        if isinstance(pump, CommandPumpToken):
            pump = self.cmd_pump
        fut = None
        # If we expect a reply to this event, we need to do some extra bookkeeping.
        # There are apparently some commands for which we can never expect to get a reply.
        # Don't add a reqid or reply fut map entry in that case, since it will never be resolved.
        if expect_reply:
            # If you don't pass in a dict for data, we have nowhere to stuff `reqid`.
            # That means no reply tracking, meaning no future.
            if not isinstance(data, dict):
                raise ValueError(f"Must send a dict in `data` if you want a reply, you sent {data!r}")
            # We need to mutate the dict, make a copy so that we don't mess with the caller's version.
            data = data.copy()
            # Tell the viewer the pump to send replies to
            data["reply"] = self._reply_pump

            req_id = self._gen_reqid()
            data["reqid"] = req_id

            fut = asyncio.Future()
            # The future will be cleaned up when the Future is done.
            fut.add_done_callback(self._cleanup_request_future)
            self._reply_futs[req_id] = fut

        self._protocol.write_message(pump, data)
        return fut

    def _gen_reqid(self) -> Any:
        return uuid.uuid4()

    def listen_scoped(self, source_pump: str):
        return LEAPListenContextManager(self, source_pump)

    async def listen(self, source_pump: PUMP_NAME_TYPE) -> LEAPListener:
        """Start listening to `source_pump`, placing its messages in the returned asyncio Queue"""
        assert self.connected
        if isinstance(source_pump, CommandPumpToken):
            source_pump = self.cmd_pump

        listener_details = self._pump_listeners[source_pump]
        had_listeners = bool(listener_details.listeners)
        listener = LEAPListener()
        listener_details.listeners.add(listener)

        if not had_listeners:
            # Nothing was listening to this before, need to ask for its events to be
            # sent over LEAP.
            await self.command(
                COMMAND_PUMP,
                "listen",
                {
                    "listener": listener_details.name,
                    "source": source_pump,
                },
            )
        return listener

    async def stop_listening(self, listener: LEAPListener) -> None:
        """Stop sending a pump's messages to msg_queue, potentially removing the listen on the pump"""
        for source_pump, listener_details in self._pump_listeners.items():
            listeners = listener_details.listeners
            if listener in listeners:
                listeners.remove(listener)
                listener.close_queue()
                if self.connected and not listeners:
                    # Nobody cares about these events anymore, ask LEAP to stop sending them
                    await self.command(
                        COMMAND_PUMP,
                        "stoplistening",
                        {
                            "listener": listener_details.name,
                            "source": source_pump,
                        },
                    )
                return
        raise KeyError(f"Couldn't find {listener!r} in pump listeners")

    def handle_message(self, message: Any) -> bool:
        """Handle an inbound message and try to route it to the right recipient"""
        if not isinstance(message, dict):
            logging.warning(f"Received a non-map message: {message!r}")
            return False

        pump = message.get("pump")
        data = message.get("data")
        if pump == self._reply_pump:
            # This is a reply for a request
            if not isinstance(data, dict):
                logging.warning(f"Received a non-map reply over the reply pump: {message!r}")
                return False

            # reqid can tell us what future needs to be resolved, if any.
            fut = self._reply_futs.get(data.get("reqid"))
            if not fut:
                logging.warning(f"Received a reply over the reply pump with no reqid or future: {message!r}")
                return False
            # We don't actually care about the reqid, pop it off
            data.pop("reqid")
            # Notify anyone awaiting the response
            fut.set_result(data)
            return True

        # Might be related to a listener we registered
        # Don't warn if we get a message with an empty listener_details.queues because
        # We may still be receiving messages from before we stopped listening
        # The main concerning case if is we receive a message for something we _never_
        # registered a listener for.
        elif (listener_details := self._pump_listeners.get(pump)) is not None:
            for listener in listener_details.listeners:
                listener.put_nowait(data)
            return True
        else:
            logging.warning(f"Received a message for unknown pump: {message!r}")
        return False

    def _cleanup_request_future(self, req_fut: asyncio.Future) -> None:
        """Remove a completed future from the reply map"""
        for key, value in self._reply_futs.items():
            if value == req_fut:
                del self._reply_futs[key]
                return


class LEAPListenContextManager(AsyncContextManager[Callable[[], Awaitable[Any]]]):
    """Helper for registering and unregistering a listener within a specific scope"""

    def __init__(self, client: LEAPClient, source_pump: str):
        self._client = client
        self._source_pump = source_pump
        self._listener: Optional[LEAPListener] = None

    async def __aenter__(self) -> LEAPListener:
        self._listener = await self._client.listen(self._source_pump)
        return self._listener

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        try:
            await self._client.stop_listening(self._listener)
        except KeyError:
            pass


class ConnectionStatus(enum.Enum):
    READY = enum.auto()
    CONNECTING = enum.auto()
    CONNECTED = enum.auto()
    DISCONNECTED = enum.auto()


class LEAPListener:
    """Wrapper for queue.get() that cancels if the client disconnects while `await`ing"""

    def __init__(self):
        self._queue = asyncio.Queue()
        self._shutdown_event = asyncio.Event()

    def close_queue(self):
        if not self._shutdown_event.is_set():
            self._shutdown_event.set()

    async def get(self) -> Any:
        # Don't yield if we already have a message ready
        if not self._queue.empty():
            msg = self._queue.get_nowait()
            self._queue.task_done()
            return msg

        if self._shutdown_event.is_set():
            raise asyncio.QueueEmpty("Listener is closed and has no queued messages")

        # Wait for a queue entry to be ready, or for client shutdown
        queue_fut = asyncio.create_task(self._queue.get())
        shutdown_fut = asyncio.create_task(self._shutdown_event.wait())
        done, pending = await asyncio.wait([shutdown_fut, queue_fut], return_when=asyncio.FIRST_COMPLETED)
        if done != {queue_fut}:
            # Shutdown happened before the queue got populated
            queue_fut.cancel()
            raise asyncio.CancelledError("Client disconnected while waiting for event")
        # We found a queue entry, don't care if shutdown happens anymore.
        shutdown_fut.cancel()
        # Consumption is completion for these queues.
        self._queue.task_done()
        # Re-awaiting is fine, it'll return the previous result.
        return await queue_fut

    def empty(self) -> bool:
        return self._queue.empty()

    def put_nowait(self, val: Any) -> None:
        assert not self._shutdown_event.is_set()
        self._queue.put_nowait(val)


@dataclasses.dataclass
class ListenerDetails:
    # We can only have one listener with a given name active at a time. Give each listener a unique name.
    name: Optional[str] = dataclasses.field(default_factory=lambda: "PythonListener-%s" % uuid.uuid4())
    listeners: Set[LEAPListener] = dataclasses.field(default_factory=set)


__all__ = [
    "COMMAND_PUMP",
    "CommandPumpToken",
    "PUMP_NAME_TYPE",
    "LEAPListenContextManager",
    "LEAPListener",
    "LEAPClient",
]
