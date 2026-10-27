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
| **Race** | two pre-established connections act on the same signal: one has pre-sent 499 bytes and sends the last byte, the other sends all 500 |
| **Abort** | send 499 bytes, pause, then close the connection without the last byte |

For split messages the pause models the time **before the decision to trade**.
Each trial records `decision_ms` (the moment the client decides: before a
complete write, or just before the final byte) and reports
`decision_to_response_ms` and `decision_to_accept_ms` (until the server has the
whole message and has finished processing it). The UI defaults to decision →
response; total time from the first byte is one click away.

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

## 3. Front-loading: pre-sending all but the last byte

Front-loading is a standard high-frequency trading technique. Traders open a connection and send most of an order (for example an HTTP
request missing its final byte) **before** they know whether they will trade.
If they decide to trade, only the last byte has to travel. If they decide not
to, they close the connection and the server discards the incomplete message.

The clock that matters is **decision → response**. The 499 bytes were sent
while the trader was still deciding, so they cost nothing. After the decision a
front-loaded order is ahead in two ways:

- **On the wire:** 1 byte instead of 500. One minimal packet, less
  serialisation time at every hop, nothing to fragment. On a real network this
  is a direct, repeatable saving over a competitor sending the full order.
- **At the receiver:** the headers and order fields were already parsed and
  validated while waiting (experiment D), so almost nothing is left to do when
  the last byte arrives. Decision → response drops by about the preparation time.

This lab runs over loopback on one machine, where moving 499 extra bytes takes
microseconds, so the wire-time part is too small to measure here. The
receiver-side part is fully visible.

**Race.** When two clients act on the same signal, the pre-sent order is
accepted first whenever the server did real preparation work in advance, by a
margin close to that work. With no server-side preparation, the only
difference left is wire time, which loopback reduces to microseconds, so the
winner follows which client the process happened to run first. The lab reports
wins for each scheduling order so this is visible rather than hidden. On a real
network that wire-time difference is exactly the edge traders are buying.

**Abort.** An incomplete message is never acted on. The servers count messages
discarded because the connection closed before the final byte, and the lab
checks that every aborted order was discarded and none was processed.

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

Measured on 2026-10-27 on loopback, Fedora 44 workstation, TCP_NODELAY on,
10 ms of server preparation where noted. Medians in milliseconds.

| Experiment (raw TCP) | Decision → response |
|---|---|
| Complete message, pre-established connection, 10 ms prep | 10.7 |
| Pre-sent 499 bytes, server prepares after the last byte | 11.8 |
| Pre-sent 499 bytes, server prepares while waiting | 0.95 |

| Race on the same signal | Result |
|---|---|
| 10 ms server prep | pre-sent won 60/60; margin ≈ 11.4 ms (raw TCP), ≈ 13.1 ms (HTTP) |
| No server prep | 30/60: decided by which client ran first, not by the bytes |

| Abort | Result |
|---|---|
| Raw TCP and HTTP | 20/20 incomplete orders discarded, 0 acted on |

What these runs showed: front-loading with server-side preparation cut
decision → response from about 11 ms to under 1 ms and won every race on the
same signal. Without preparation, loopback hides the wire-time saving; on a
real network that saving is added on top.

## 9. Safety boundaries

The client can only target this process's own loopback endpoints (the host is
fixed to 127.0.0.1/::1/localhost by configuration validation). Limits: ≤ 500
trials, ≤ 50 warm-up, ≤ 8 concurrent connections, ≤ 64 KiB messages, ≤ 1 s split
delay, ≤ 200 ms server work, ≤ 120 s estimated run time, ≤ 10 s per-trial
timeout, one run at a time.
