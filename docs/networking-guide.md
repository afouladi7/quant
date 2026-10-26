# Networking Guide: the TCP Performance Lab

## 1. TCP is a byte stream

TCP delivers an ordered stream of **bytes**. It has no idea where one
application message ends and the next begins. Consequently:

- one application `write()` does **not** guarantee one TCP segment;
- two `write()` calls do **not** guarantee two segments (they may be merged), and
  one large write may be split across many segments;
- the receiver may get the bytes of one message across several `read()` calls,
  or bytes of two messages in one read.

The application therefore needs **message framing**: a way to know when a
message is complete. MarketLab's raw-TCP protocol uses a 16-byte header that
declares the total message length; HTTP/1.1 uses the `Content-Length` header.
The server in either case **cannot act** on a 500-byte order until all 500 bytes
have arrived.

## 2. What the lab measures and how

| Experiment | What the client does |
|---|---|
| **A** complete message | one write of all 500 bytes |
| **B** split message | write 499 bytes, optional pause (0 ms allowed), write the final byte |
| **C** pre-established connection | connect *before* the measured request; reuse it |
| **D** useful early work | like B, but the server starts preparation work once 499 bytes are in |

Cold-connection runs open a new TCP connection per trial and include the
handshake (`connect_ms`) in the measured time; reused-connection runs establish
the connection first and exclude it. The two are always reported separately.

Timestamps come from `time.monotonic_ns()`. The benchmark client and both
servers (raw TCP on loopback port 9500; HTTP on the backend's own port) run **in
the same process**, so client and server readings come from one clock and can be
subtracted directly.

Per trial: connect, first/last application write, server first receive, server
"all but last byte" available, full message available, preparation and
processing intervals, time to first response byte, first-to-last response byte,
total. Summaries: n, min, median, mean, standard deviation, p25/p75, and p90
(n ≥ 10), p95 (n ≥ 20), p99 (n ≥ 100), plus error and timeout rates. Warm-up
trials are excluded.

**Not observed:** TCP segments, ACKs or kernel queues (no packet capture, which
would need privileges). "Writes" are application writes. Over HTTP the server
timestamps mark when the ASGI application *consumed* body chunks from
uvicorn's buffer, not socket arrival; uvicorn may merge the 499- and 1-byte
writes into one chunk.

## 3. Why splitting 499 + 1 rarely helps

If the server must wait for the final byte, the request cannot complete before
that byte arrives. Splitting therefore adds at least the pause between the two
writes, plus a second write's overhead, and can trigger Nagle/delayed-ACK
interactions (§5). It can only help if the server does **useful work** with the
first 499 bytes while the last one is in flight (experiment D). That is
overlapping computation with communication. TCP does not get faster.

## 4. Connection establishment and persistent connections

A new TCP connection costs a handshake (SYN, SYN-ACK, ACK: about one round trip)
before data flows, plus kernel and application setup. TLS adds more round trips.
Reusing a **persistent** connection (HTTP keep-alive, or a long-lived raw socket)
removes that cost from every request after the first.

## 5. Nagle's algorithm, delayed ACKs and TCP_NODELAY

- **Nagle's algorithm** holds back a small segment while earlier sent data is
  still unacknowledged, to coalesce tiny writes.
- **Delayed ACK**: receivers often wait (Linux: up to ~40 ms) before
  acknowledging, hoping to piggyback the ACK on a reply.
- Together, a sender that does *write, write, wait for reply* can stall about
  40 ms: the second write waits for an ACK that the receiver is deliberately
  delaying.
- **TCP_NODELAY** disables Nagle on a socket. MarketLab sets it on the client
  socket when the option is ticked, reads it back with `getsockopt`, and
  reports the value actually applied. For raw TCP the server applies it too.

### A real example found while building this lab

In development, HTTP keep-alive requests took a median of ~45 ms even though the
first response byte arrived after ~4 ms. A socket-level test showed the 126-byte
response headers arriving, then the 338-byte body ~40 ms later: the
Nagle + delayed-ACK signature. The cause was traced to uvicorn under `--reload`,
which creates its listening socket with protocol number 0. asyncio only enables
TCP_NODELAY on accepted sockets whose protocol is `IPPROTO_TCP`, so those
sockets kept Nagle on. In the container image (uvicorn without `--reload`) the
same requests took ~1.2 ms. The lab flags any run whose first-to-last response
byte gap exceeds 20 ms, but it cannot prove the cause for a particular run
without packet capture.

## 6. Latency distributions and noise

Latency is a **distribution**, not a number. Look at the median for typical
behaviour and at p90/p95/p99 for tails. Small samples cannot support strong
claims. Sources of noise here include OS scheduling, CPU frequency scaling, the
shared event loop (client and server compete for it), garbage collection,
container CPU limits, and other workloads on the host. Re-run experiments and
compare distributions, not single values.

## 7. Transport delay vs. application processing

Total time = connection setup + time to deliver the full message + server
processing + response delivery. The phase table separates these: *server waited
for last byte* is transport/client behaviour; *preparation* and *processing*
are application work. Shaving transport time does not help if processing
dominates, and vice versa.

## 8. Example results (one machine, one day; yours will differ)

Measured on 2026-10-25 with the Preset 5 suite, 40 trials each, TCP_NODELAY on,
loopback, Fedora 44 workstation. Medians in milliseconds.

| Experiment | Raw TCP (dev) | HTTP (backend container on kind) |
|---|---|---|
| A complete, cold connection | 0.79 | 2.57 |
| C complete, pre-established | 0.25 | 1.23 |
| B split 499+1, no pause | 0.27 | 1.26 |
| B split, 20 ms pause, 10 ms prep after | 32.8 | 34.9 |
| D split, 20 ms pause, 10 ms prep during | 22.4 | 23.4 |

What these particular runs showed: a pre-established connection saved ~0.5 ms
(raw) and ~1.3 ms (HTTP); an unpaused split cost almost nothing on loopback; the
pause was paid in full; overlapping the 10 ms of preparation recovered ~10 ms of
it. On a real network, connection setup costs at least one round trip, so the
reuse benefit grows with distance.

## 9. Safety boundaries

The client can only target this process's own loopback endpoints (the host is
fixed to 127.0.0.1/::1/localhost by configuration validation). Limits: ≤ 500
trials, ≤ 50 warm-up, ≤ 8 concurrent connections, ≤ 64 KiB messages, ≤ 1 s split
delay, ≤ 200 ms server work, ≤ 120 s estimated run time, ≤ 10 s per-trial
timeout, one run at a time.
