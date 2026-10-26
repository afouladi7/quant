"""MarketLab benchmark wire protocol (raw TCP), and the server-side message assembler.

Message = 16-byte header + filler payload; ``total_len`` covers the whole message,
so the default 500-byte message is 16 header bytes + 484 payload bytes.

    offset size field
    0      2    magic  b"ML"
    2      1    version (1)
    3      1    flags  bit0 = early work allowed, bit1 = server sets TCP_NODELAY
    4      2    prep_ms  (preparatory work)
    6      2    proc_ms  (processing after the message is complete)
    8      4    total_len
    12     4    seq

Response = 4-byte big-endian length + JSON object with server-side timestamps
(monotonic nanoseconds from the same clock the in-process client uses).

TCP is a byte stream: the server treats bytes as they arrive and only considers
the message complete when exactly ``total_len`` bytes have been received,
however many reads/segments that took.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"ML"
VERSION = 1
HEADER = struct.Struct("!2sBBHHII")
HEADER_LEN = HEADER.size  # 16
FLAG_EARLY = 0x01
FLAG_NODELAY = 0x02
MIN_MESSAGE = HEADER_LEN + 1
MAX_MESSAGE = 65_536


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    flags: int
    prep_ms: int
    proc_ms: int
    total_len: int
    seq: int

    @property
    def early(self) -> bool:
        return bool(self.flags & FLAG_EARLY)

    @property
    def nodelay(self) -> bool:
        return bool(self.flags & FLAG_NODELAY)


def build_message(total_len: int, seq: int, *, prep_ms: int = 0, proc_ms: int = 0, early: bool = False, nodelay: bool = False) -> bytes:
    if not MIN_MESSAGE <= total_len <= MAX_MESSAGE:
        raise ProtocolError(f"message length must be {MIN_MESSAGE}..{MAX_MESSAGE}")
    flags = (FLAG_EARLY if early else 0) | (FLAG_NODELAY if nodelay else 0)
    head = HEADER.pack(MAGIC, VERSION, flags, prep_ms, proc_ms, total_len, seq)
    filler = bytes((seq + i) % 251 for i in range(total_len - HEADER_LEN))
    return head + filler


def parse_header(data: bytes) -> Header:
    if len(data) < HEADER_LEN:
        raise ProtocolError("incomplete header")
    magic, version, flags, prep, proc, total, seq = HEADER.unpack(data[:HEADER_LEN])
    if magic != MAGIC or version != VERSION:
        raise ProtocolError("bad magic/version")
    if not MIN_MESSAGE <= total <= MAX_MESSAGE:
        raise ProtocolError("invalid total length")
    if prep > 1000 or proc > 1000:
        raise ProtocolError("work durations too large")
    return Header(flags, prep, proc, total, seq)


class MessageAssembler:
    """Accumulates stream chunks; knows when the prefix (all but the last byte) and the whole message are present.

    It never reports completion early and rejects bytes beyond the declared length
    of the current message (pipelining is not part of this lab protocol).
    """

    def __init__(self) -> None:
        self.buf = bytearray()
        self.header: Header | None = None

    def feed(self, chunk: bytes) -> None:
        self.buf += chunk
        if self.header is None and len(self.buf) >= HEADER_LEN:
            self.header = parse_header(bytes(self.buf))
        if self.header is not None and len(self.buf) > self.header.total_len:
            raise ProtocolError("received more bytes than the declared message length")

    @property
    def received(self) -> int:
        return len(self.buf)

    @property
    def prefix_ready(self) -> bool:
        return self.header is not None and len(self.buf) >= self.header.total_len - 1

    @property
    def complete(self) -> bool:
        return self.header is not None and len(self.buf) == self.header.total_len
