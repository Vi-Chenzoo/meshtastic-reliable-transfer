# Transfer protocol, version 7

Reference implementation: [`prototype/protocole.py`](prototype/protocole.py) and
[`prototype/raid6.py`](prototype/raid6.py). C++ port: [`cpp/`](cpp/). Every reference to Meshtastic's code points
to a file and line of firmware **2.8.3** (commit `51ac6ea`) or of the Python client.

## 1. Purpose

Deliver a content of a few KB (up to 16 383 chunks, about 3.6 MB) from one Meshtastic node to another, using as
little airtime as possible per useful byte, without ever saturating the channel. Compression is done by the
application before sending.

## 2. Transport

- Each protocol frame is the payload of a Meshtastic **direct** message, port `PRIVATE_APP` (256) for now,
  **without `want_ack`**: the protocol handles its own reliability.
- **At most 219 bytes per frame**, not the 233 of `Data.payload`. Between two nodes that know each other's keys, a
  direct message is encrypted with the public key, which adds 12 bytes (`src/mesh/Router.cpp:1336-1338`,
  `MESHTASTIC_PKC_OVERHEAD` in `src/mesh/RadioInterface.h:23`), and the firmware adds the `bitfield` field to
  everything it sends (`src/mesh/Router.cpp:1236`). Encoded `Data` = frame + 8 bytes (portnum 3, length 3,
  bitfield 2), and frame + 8 + 16 (radio header) + 12 must be ≤ 255. Checked by
  [`prototype/tests/test_tailles.py`](prototype/tests/test_tailles.py).
- **`BACKGROUND` priority** on every frame, so ordinary messages go first. The Python client takes a priority
  (`sendData(priority=...)`, `meshtastic/mesh_interface.py:520`, copied into the packet at `:576-577`); its default
  is `RELIABLE` (70), above ordinary traffic. The firmware keeps a priority set by the client (`fixPriority` only
  touches `UNSET`, `src/mesh/MeshPacketQueue.cpp:47`). When the queue is full, a higher-priority packet evicts the
  last `BACKGROUND` frame (`src/mesh/MeshPacketQueue.cpp:153-169`): for the protocol it is an ordinary loss.
- The protocol runs end to end between the two clients and does not depend on the route: the bench results of §8
  used Meshtastic's own relaying over 2 hops. Relay stations that store a whole content before forwarding it one
  hop at a time (`hop_limit` 0) are separate work, not part of this specification.

## 3. Frames

Big-endian integers. `id` identifies the transfer (1 byte, chosen by the sender).

- **HEADER** `0x01`: `id`(1) `size`(4, bytes of content) `chunks`(2) `group`(1, = 8) `reserved`(1)
  `fingerprint`(4, CRC32 of the content) `chunk_size`(1). 15 bytes; then, optionally, `final_recipient`(4) when the
  content goes through a relay station. A receiver without room for the content does not answer READY.
- **READY** `0x02`: `id`(1) `first`(2), then 1 byte per group already started from `first`. `first` is the first
  group the receiver does not have in full (0 for a new content). Each following byte is a bitmap of the chunks it
  is missing in that group (0 = complete). The sender only sends those, and skips complete groups.
- **CHUNK** `0x03`: `id`(1) `number`(2), then the data. **4 bytes of header, 215 useful bytes.**
  - bit 15 of the number: **last chunk** of the content;
  - bit 14: **parity** chunk; then bits 13..1 = group number, bit 0 = 0 for P, 1 for Q;
  - otherwise bits 13..0 = number of the data chunk (0 to 16 382).
- **Chunk size** (`chunk_size` in the HEADER): 215 bytes at most. A small content of 2 to 8 chunks (one group) is cut
  into **equal chunks**, the remainder in the first ones: 450 bytes give 3 × 150 instead of 215 + 215 + 20, and
  533 bytes give 178, 178, 177. Parity chunks are as long as the longest chunk of their group, so they shrink too:
  −8 % airtime for 450 bytes, −3 % for 533 bytes (LONG_FAST). Above 8 chunks the gain disappears (−0.7 to +0.8 %,
  LoRa rounds airtime by symbols), so the size stays 215. Every sender must apply the same rule: the fingerprint of
  a resume includes the chunk size.
- **SUMMARY** `0x04`: `id`(1) `first`(2) `groups_judged`(2) `received`(2) `expected`(2), then **1 byte per group from
  `first` to `groups_judged` − 1**: bit k = chunk k of the group is missing and cannot be rebuilt; 0 = group complete
  or rebuilt. Groups before `first` are all complete. At most 209 groups per summary (219 bytes); a longer content
  is described over several summaries.
- **QUESTION** `0x05`: `id`(1). The sender asks for a full summary.

**Resume.** The receiver recognises a content it has already started by its **fingerprint** (CRC32, size, chunk
size), even under another `id` or from another sender (another relay). The sender starts at group `first` and, in
started groups, sends only the missing chunks. A content already delivered: READY with `first` = number of groups,
then the final SUMMARY at once. Tests: [`prototype/tests/test_reprise.py`](prototype/tests/test_reprise.py).

## 4. Parity (RAID 6 style)

For each group of 8 data chunks, 0, 1 (P) or 2 (P and Q) parity chunks, computed byte by byte in GF(2⁸)
(polynomial 0x11D, generator 2), as in Linux RAID 6: P = ⊕ Dᵢ, Q = ⊕ gⁱ·Dᵢ. Short chunks are padded with zeros.
The receiver rebuilds 1 lost chunk with P (or Q) and 2 with P and Q.

**Adaptation**: 1 parity chunk until the first summary arrives; then, from the loss rate the receiver reports
(`1 − received / expected`): 0 below 2 %, 1 below 7 %, 2 above. 2 from the start if the HEADER had to be resent
(bad link).

## 5. Flow

```
 Sender                                               Receiver
 HEADER ────────────────────────────────────────────▶ creates the transfer
        ◀──────────────────────────────────────────── READY
 window 0: groups 0-3 (data + parity) ──────────────▶
 window 1: groups 4-7                 ──────────────▶ at the first new chunk of each block of 32:
        ◀──────────────────────────────────────────── SUMMARY (groups already passed)
 missing chunks + next window ──────────────────────▶
 …                                                    at the LAST chunk:
        ◀──────────────────────────────────────────── SUMMARY (all groups)
 missing chunks ────────────────────────────────────▶ … until a SUMMARY with nothing missing:
                                                      content checked (CRC32)
```

- **Windows**: 4 groups per window, 2 windows ahead at the start, then one window per summary received.
- **Checkpoint**: the receiver sends a SUMMARY at the first **new** chunk of each block of 32. A resent chunk never
  triggers a checkpoint (otherwise checkpoint → resend → checkpoint loops, seen in simulation). It only judges the
  groups whose parity has necessarily passed.
- **Resend**: only the data chunks reported missing, and only in groups already sent. A group already resent is not
  resent again before the resend delay (it may still be on its way).
- **End**: the sender considers the transfer done at the SUMMARY that judges every group and reports none missing;
  the receiver delivers the content only if the CRC32 matches.

## 6. Timers and failure

- Waiting for an answer starts at the **real end of transmission** of the frames (`emission_terminee`), not when
  they are queued: 57 chunks on LONG_FAST take about 2 minutes to leave.
- **Handshake**: without READY, the HEADER is resent every 20 s; the receiver resends READY (at most 3 times) if no
  chunk arrives within 20 s.
- **Resend delay**: 2.5 times the round trip between the last HEADER sent and the READY, between 15 and 60 s.
  Without news during that delay: QUESTION (sent after the next window, if there is one).
- **Final summary**: at the last chunk, if nothing is missing, at once; otherwise after a silence of twice the usual
  gap between frames (median of the last 8), at least 5 s, so that the parity of the last group can arrive. Any
  resent chunk after that restarts the wait, and a chunk that completes the content triggers the summary at once.
- After 10 resends without an answer: failure.

## 7. Airtime budget

Class `Budget` in [`prototype/protocole.py`](prototype/protocole.py), one per device, checked before **every**
frame. Same thresholds as the firmware's polite modules (`src/airtime.h:231-232`, `src/airtime.cpp:304-331`):
- **5 % of the sliding hour** for our frames (180 s per hour). The other half of the 10 % EU_868 duty cycle stays
  for ordinary messages;
- **25 % of the channel**: after a frame of duration d, the device stays silent for 3 d (a steady pace rather than
  bursts);
- **device telemetry** (`DeviceMetrics`, sent to the client every minute,
  `src/modules/Telemetry/DeviceTelemetry.h:43`): if the channel is at 25 % or more, or the device's own
  transmissions at 5 % or more, the sender waits for the next measurement. Short replies (READY, SUMMARY) do not
  wait for this measurement.

Checked in simulation on 10 transfers of 30 KB: at worst 179.9 s of transmission in an hour (cap 180 s). The budget
adds no airtime: pauses do not cause resends.

## 8. Results

Bench: the real 2.8.3 firmware built for Linux (`meshtasticd -s`, `SimRadio`); a relay script plays the air with
per-link loss and LoRa airtime; chain A - R - B, LONG_FAST, 4 KB, 5 runs per case. Compared with what an app would
do today (one acked Meshtastic message per chunk):
- 10 % loss: acked messages 2 complete files out of 5, 125 s of airtime; this protocol 5 out of 5 in 151 s,
  109 s of airtime;
- 20 % loss: acked messages 0 out of 5, 133 s of airtime; this protocol 5 out of 5 in 205 s, 127 s of airtime.

The acked messages also produced "false successes" (1.4 to 2.2 per transfer): the implicit ack only proves that the
first hop heard the packet (`src/mesh/ReliableRouter.cpp:58`).

In-memory simulation ([`prototype/simulation.py`](prototype/simulation.py)), one hop, LONG_FAST, within the budget:
10 KB in about 7 min, 30 KB in about 1 h 10. Above about 10 KB a faster preset is needed.

**Not yet measured on real radios.**

## 9. Open questions

1. Port number: keep `PRIVATE_APP`, or reserve a port for file transfer?
2. Format: the existing `ChunkedPayload` (`protobufs/meshtastic/mesh.proto:3895-3946`) or this compact format? With
   the sizes that really fit (215 useful bytes here, 216 for `ChunkedPayload`), both cost the same airtime in
   simulation (`prototype/simulation.py`): the choice is about compatibility, not efficiency. A full
   `ChunkedPayload` with a 228-byte chunk no longer fits into `Data.payload`.
3. Several transfers at once: the 1-byte `id` allows it; the prototype handles one at a time per peer.
4. Adaptation thresholds and window size: to be tuned on real hardware.
