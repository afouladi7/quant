"""In-process raw TCP benchmark server (loopback only).

Per message it records: first byte received, prefix (all but the last byte)
available, complete message available, preparation and processing intervals,
and when the response was written. The operation is committed only after
``MessageAssembler.complete`` is true.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
import time
from typing import Any

from app.tcplab.protocol import MessageAssembler, ProtocolError
from app.tcplab.work import do_work

log = logging.getLogger(__name__)
READ_SIZE = 65_536


class TCPBenchServer:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._server: asyncio.base_events.Server | None = None
        self.connections = 0
        self.messages = 0
        self.premature_commits = 0  # must always stay 0; exposed for verification

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, self.host, self.port, limit=READ_SIZE)
        sock = self._server.sockets[0]
        self.port = sock.getsockname()[1]
        log.info("TCP lab server listening", extra={"host": self.host, "port": self.port})

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    @property
    def running(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        sock: socket.socket = writer.get_extra_info("socket")
        try:
            while True:
                result = await self._one_message(reader, sock)
                if result is None:
                    break
                result["response_write_ns"] = time.monotonic_ns()
                body = json.dumps(result).encode()
                writer.write(struct.pack("!I", len(body)) + body)
                await writer.drain()
                self.messages += 1
        except (ProtocolError, ConnectionError, asyncio.IncompleteReadError) as exc:
            log.debug("tcp lab connection ended: %s", exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    async def _one_message(self, reader: asyncio.StreamReader, sock: socket.socket) -> dict[str, Any] | None:
        asm = MessageAssembler()
        first_rx = prefix_ns = None
        reads = 0
        prep_task: asyncio.Task | None = None
        nodelay_applied: bool | None = None
        while not asm.complete:
            chunk = await reader.read(READ_SIZE if asm.header is None else asm.header.total_len - asm.received)
            if not chunk:
                return None
            now = time.monotonic_ns()
            reads += 1
            if first_rx is None:
                first_rx = now
            asm.feed(chunk)
            if asm.header is not None and nodelay_applied is None and asm.header.nodelay and sock is not None:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                nodelay_applied = bool(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))
            if prefix_ns is None and asm.prefix_ready:
                prefix_ns = now
                h = asm.header
                assert h is not None
                if h.early and h.prep_ms and prep_task is None:
                    # Useful early work: prepare using the prefix while the last byte is in flight.
                    prep_task = asyncio.create_task(do_work(bytes(asm.buf[: h.total_len - 1]), h.prep_ms))
        complete_ns = time.monotonic_ns()
        h = asm.header
        assert h is not None
        if prep_task is not None:
            prep_start, prep_end, _ = await prep_task
        else:
            prep_start, prep_end, _ = await do_work(bytes(asm.buf), h.prep_ms)
        if not asm.complete:  # defensive: commit only on a complete message
            self.premature_commits += 1
            raise ProtocolError("attempted to commit an incomplete message")
        proc_start, proc_end, digest = await do_work(bytes(asm.buf), h.proc_ms)
        return {
            "seq": h.seq,
            "bytes": asm.received,
            "reads": reads,
            "first_rx_ns": first_rx,
            "prefix_ready_ns": prefix_ns,
            "complete_ns": complete_ns,
            "prep_start_ns": prep_start,
            "prep_end_ns": prep_end,
            "proc_start_ns": proc_start,
            "proc_end_ns": proc_end,
            "early_work": h.early,
            "server_nodelay_applied": nodelay_applied,
            "digest": digest,
        }
