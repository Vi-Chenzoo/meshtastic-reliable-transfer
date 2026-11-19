# Validation of the final firmware build on two Heltec V4 (19 November 2026)

Raw radio journals and the analyses of the runs made on 19 Nov 2026 to validate the build we intend to ship (first part), then of complementary runs made the same afternoon and evening (second part: USB buffer, control-frame priority, channel scans, ESP-NOW meeting hello), on the same two Heltec V4 boards as in
[`../2026-11-18-heltec-v4`](../2026-11-18-heltec-v4/README.md) (same setup, same journal format, same analysis scripts: see that folder).
Follow-up to [discussion #12338](https://github.com/meshtastic/firmware/discussions/12338). License GPL-3.0. Copyright (C) 2026 SoCodeIA and Vincent PERRIN.

## One precision on our reply of 19 Nov

In that reply we wrote that widening the contention window by 2 bits for bulk frames costs "nothing we could measure" at the normal pace of the protocol. That was measured on a
7.5 KB transfer in **one direction** (`b4` and `b5` in the previous folder: 325 s both). With **both boards sending at the same time** we do measure a cost:
about 6 % more time per transfer on average (103.0 s against 96.8 s over six sends per setting), about 1 % on board 1 and about 11 % on board 2 (details below).
No collision occurred at that pace with either setting, so the wider window brought no visible benefit there; its benefit shows in saturated bursts only.

## What was tested

- **Two builds of the same source tree.** The *production* build (2.8.3.2) and a *test* build (v7) that is the same code plus the microsecond radio journal, the burst test mode and the
  test-setting order. Both have: control frames (ready, summary, question) queued with priority RESPONSE, a contention window widened by **2 bits by default** for bulk (BACKGROUND) frames,
  a 4,096-byte USB receive buffer. Only the test build records a journal, so only its runs have files in this folder.
- Two Heltec V4 boards a few centimetres apart, EU_868, ESP-NOW off, LoRa only, our protocol over `PRIVATE_APP`, `hop_limit` 0. Boards were flashed over USB (hash verified); region, preset and
  channels were read back unchanged before and after.
- Rolling airtime budget: at most 150 s per board over 60 minutes (the highest value seen was 106.7 s).

## Raw numbers

**P1, production build, 7,500 random bytes, one direction, LONG_FAST.** Delivered in 325 s, 81.7 s of airtime, 41 frames, 0 retransmission, file identical.
Same figures as the reference run `b5` of the previous folder.

**P2 / P2bis, production build, 2,048 bytes each way at the same time, LONG_FAST** (figures printed by our transfer tool; the production build has no journal, and the tool output contains board
identifiers, so it is not included here).
- P2 (first version of the tool): both files arrived identical within about 1 min 45 s, but board 1's own send never received its final confirmation and ended with "abandon" after about
  8 more minutes (40 frames, 37.0 s of airtime in total). Cause on our side: the tool on board 2 exited as soon as it had sent its file *and* received the other, so nobody answered board 1's
  QUESTION frames any more. We believe the tool, not the firmware, was at fault; we cannot see the frame that was missing because the production build has no journal.
- Fix: each tool now stays 120 s listening after it has finished sending and receiving (`--apres-duplex`, default 120 s).
- P2bis (production build, fixed tool): board 1 to board 2 delivered in 107 s (16 frames, 26.1 s of airtime), board 2 to board 1 in 96 s (15 frames, 25.6 s); both files identical; clean end.

**E1, test build v7 at its default setting, MEDIUM_FAST, symmetric saturation** (each board sends 60 numbered packets of 17 B with no pause; no setting order sent; runs `f1` to `f3`):
- 366 transmissions, 188 strict conflicts, **2 collisions = 0.55 % per frame** (start gaps 0.36 ms and 1.15 ms). The 4 frames lost in these runs are exactly these two collisions (both frames of a collision
  are lost); no frame lost without a cause.
- Previous series, same test (`e01` to `e23`), setting sent by a test order: +0 bits 29 collisions out of 366 (7.9 %), +1 bit 16 (4.4 %), +2 bits 4 (1.1 %). 2 against 4 collisions is not a difference we can
  claim; 2 against 29 is.
- The default is active: the median pause between two frames of the same burst is 376 to 588 ms in `f1`-`f3`, against 379 and 476 ms in the earlier +2 bit run `e21` and 115 and 169 ms in the +0 run `e01`.
- Measured airtime 9,777 ms per board and run against 9,776 ms computed from the Semtech formula (+0.02 %).

**E2, test build v7, two-way transfer, LONG_FAST** (each board sends a 2,048-byte random file to the other, the two started about 2 s apart; setting +2 bits or +0 bit sent by a test order after clearing the
journal; order +2, +0, +2, +0, +2, +0, at least 10 minutes apart except `g3`; runs `g1` to `g6`). In all 6 runs both files arrived identical, 0 strict conflicts, 0 collisions, 17 transmissions per board all received, no abandon.
Each run ends about 2 minutes after both files arrived (the 120 s listening time), which is not counted below.

    time to deliver each send (board 1 -> board 2 / board 2 -> board 1), frames, airtime
    +2 bits  g1: 98 s (15 frames, 25.6 s) / 106 s (16 frames, 26.1 s)
             g3: 102 s (15, 25.6 s)       / 108 s (16, 26.1 s)      <- started 14 s after g2 ended (script error on our side), run valid
             g5: 98 s (15, 25.6 s)        / 106 s (16, 26.1 s)
    +0 bit   g2: 98 s (16, 26.1 s)        / 95 s (15, 24.0 s)
             g4: 98 s (15, 24.0 s)        / 97 s (15, 24.0 s)
             g6: 98 s (16, 26.1 s)        / 95 s (15, 24.0 s)

- Mean time per send: +2 bits 103.0 s, +0 bit 96.8 s (+6 %). Board 1: 99.3 s against 98.0 s (+1 %). Board 2: 106.7 s against 95.7 s (+11 %).
- Median wait between entering the TX queue and starting to transmit (median of the six per-board medians): about 2.8 s with +2 bits, about 0.9 s with +0 bit.
- Airtime per send is 24.0 to 26.1 s in both settings.

## Second part: runs made later the same day (19 Nov, afternoon and evening)

Same two Heltec V4 boards, same setup. Two more test builds were used: **v8** and **v8b**. They are the v7 test build plus journal events only: for each channel scan (CAD) its start, end, result
(v8b adds the receiver state just before the scan), and for each ESP-NOW hello its direction, signature or verification time and what the receiver did; plus two test orders (switch the meeting reply on or off,
make a board forget its neighbours). **No other change of behaviour.** The production build is unchanged.

### U. USB receive buffer (4,096 bytes), no radio

ESP-NOW ON on both boards (signed hello every 60 s active: 10 to 13 hellos sent and 9 to 12 received per board, signature 113 ms, verification up to 182 ms). A PC tool sends bursts of 16 frames of 219 B (about 3.9 KB), 40 bursts, 3 s of silence.

    board 1 alone            640 / 640 frames received
    board 2 alone            640 / 640
    both at the same time    640 / 640 on each
    control, bursts of 30 frames (about 7.3 KB, beyond the buffer), 20 bursts: 600 / 600

3,160 frames, **0 lost, 0 duplicate, 0 damaged.** Longest read pause 410 ms. Lowest free space in the buffer: 249 bytes with 16-frame bursts, 29 bytes with 30-frame bursts (the buffer came close to full without losing anything).
**Our positive control did not reproduce a loss at 4,096 bytes**: this run cannot show that the buffer is what prevents a loss (probably the PC-side queue empties before the buffer is full, or USB flow control holds the host back).
The loss itself was seen on 18 Nov with a 256-byte buffer (4 frames of 26 lost) and not with 2,048 or 4,096. The board's internal log was off, so hellos are proven by the counters, not their coincidence with a burst.
No journal for this part (the tool outputs contain USB device paths, so they are not included).

### H. Control-frame priority, deep queue (`h1` to `h4`)

Production setting (contention window +2 bits for data), LONG_FAST, ESP-NOW off, test build v7. Board 2 has a burst of 12 frames of 219 B in its queue; board 1 sends a 1,024-byte file 42 s after the burst command; the
"ready" frame (27 B) of board 2 is queued behind the burst. Runs alternate with the priority on (`h1`, `h3`) and off (`h2`, `h4`; test option `--sans-priorite-controle` on board 2), at least 10 minutes apart.

    first "ready" frame of board 2          frames ahead in queue   wait before transmission    file delivered in
    priority ON   h1                        11                      2,069 ms                    46 s
    priority ON   h3                        11                      2,040 ms                    62 s
    priority OFF  h2                        12                      44,441 ms                   89 s
    priority OFF  h4                        12                      49,563 ms                   92 s

- With the priority the ready frame leaves after about 2 s; without it, after the whole burst (44 to 50 s at this setting), and board 1 repeats its header for lack of a "ready": 11 frames sent in `h2` against 8 in `h1`.
- Delivery time: -48 % (`h1` against `h2`) and -33 % (`h3` against `h4`). Files identical 4 of 4, 0 lost, 0 damaged, 0 collision (`h3`: one strict conflict without loss), measured airtime equal to the computed one.
- At the earlier +0-bit setting the same wait was 15.6 s with 7 frames ahead (`c1g` in the previous folder). Here each data frame ahead costs about 3.7 to 4.1 s (the widened window makes each data frame wait longer): the larger figure is not a regression of the priority.
- Two runs per condition; the queue depths are 11 and 12, not strictly equal.

### I. Channel scans (CAD) in a symmetric saturation (`i1` to `i4`, test build v8b)

MEDIUM_FAST, both boards send 80 numbered packets of 17 B with no pause (81 transmissions per board), contention window +0, +2, +0, +2 bits (`i1` to `i4`), at least 5 minutes apart, 486 to 698 events per journal out of 2,048 (no overflow). Airtime about 12 s per board and run.

- **Collisions** (both frames lost, overlap above 5 ms): +0 bit 6 and 7 (13 of 324 transmissions = 4.0 %), +2 bits 1 and 3 (4 of 324 = 1.2 %). Same order as the earlier series (7.9 % / 4.4 % / 1.1 % for 0, 1, 2 bits) and the validation runs `f1` to `f3` (2 of 366).
- **Scan duration**: median 9.3 to 9.4 ms (maximum 11.5 ms; 4 symbols + 0.5 at 2.048 ms = 9.2 ms). One "free" scan per transmitted frame (the one just before departure) and 12 to 24 "busy" scans per run and board.
  The radio is armed for reception before every scan. The preamble hold and the "peek" scan (`#11933`) were used once in the four runs: **they do not protect the scans that follow a "busy" result**.
- **Delay between the end of the last scan and the start of transmission is constant**: 3.63 to 3.72 ms (median 3.66 ms, 34 measurements over the 17 collisions).
  The end of that scan falls between -8.9 and +1.5 ms of the other board's departure (up to 1.5 ms after it, without seeing it). Our reading: a blind window of about 3.7 ms of fixed latency plus about 1.5 ms (0.7 symbol at SF9) for the scan to see a preamble already started, about 5.2 ms at SF9.
  At SF11 the same reading gives about 9 ms (deduced, not measured: SF9 is the only setting measured directly), consistent with the largest start gap seen in LONG_FAST (9.3 ms). Start gaps of the 17 collisions: -5.2 to +4.6 ms.
- **One frame lost outside a collision out of 614** (`i3`, board 1 to board 2, 40 B, preamble 41.5 ms): the receiver does a busy scan from +4.1 to +13.5 ms, then **3.4 ms later** a second one from +16.9 to +28.4 ms, which ends with only 13.1 ms = 6.4 symbols of preamble left. Lost.
- **Why a second scan so soon**: the pauses between the end of a busy scan and the next one come in multiples of the slot time 16.8 ms (0.8 to 3.5 ms; 17; 33; 49 to 52; 65 to 67; 81; 97 ms), as expected from `random(0, 2^CW) x slotTime`; a draw of 0 gives an almost immediate new scan.
  Pauses of 0.8 to 3.5 ms: 9 of 25 at +0 bit, 0 of 11 at +2 bits (the wider window makes a 0 draw four times rarer). The share seen at +0 bit is above the 1/8 expected: cause not seen, a selection effect is possible.
- **Scan analysis over every run of the folders** (`scan-analysis/receiver-scans-published-journals.txt`, redone on the published, anonymised journals: 44 runs, 3,453 frames not overlapped by a transmission of the receiver), MEDIUM_FAST (preamble 20.25 symbols = 41.5 ms):

        no busy scan at the receiver during the frame:  0 lost of 2,204
        at least one busy scan during the frame:        7 lost of 218
          preamble left at the last busy scan inside the preamble
            less than 6.5 symbols:   7 lost of 7
            6.5 symbols or more:     0 lost of 211

  LONG_FAST: 0 lost of 978 without a busy scan, 1 of 53 with one (51 of these had 10 symbols or more left; the lost one had all its scans after the end of the preamble, cause not seen).
  The threshold lies between 6.4 and 7.2 symbols with few frames around it (3 between 6.5 and 7.5 symbols); only SF9 and SF11 at 250 kHz were measured.
  Our reading, from the code and the journals, with no experiment that changes the code: a scan puts the chip out of reception, and a scan placed in the last symbols of a preamble leaves too few symbols to lock on it.

### M. Meeting hello, ESP-NOW only (`meetings/`)

Question: when a board arrives and meets a neighbour that is already there, how long until it knows that neighbour, with or without the extra "meeting" hello that the old board sends in reply to the newcomer's first hello?
Two boards, ESP-NOW on, **no LoRa transmission at all**. Board 1 is the "old" board (`oublier 0`: it forgets its neighbours and keeps its periodic hello rhythm), board 2 the "new" one (`oublier 1`: it forgets and sends its first hello within 3 s, about 1.6 s after the old one's order).
16 meetings interleaved, reply ON (`m1`, `m3`, ... `m15`) and OFF (`m2`, ... `m16`), a random wait of 0 to 60 s before each order (seed 20261119) so that the old board's periodic hello falls anywhere, 90 s of observation.

    time for the NEW board to know the old one
    reply ON  (8 meetings):  1.8, 2.8, 3.0, 3.6, 4.2, 4.3, 4.7, 4.7 s   (8 of 8, median 3.9 s)
    reply OFF (8 meetings):  5.3, 25.9, 45.9, 49.2, 50.0, 53.0 s, and never within 90 s in 2 of 8 (`m10`, `m14`)
                             (median of the six that happened: 47.5 s)

- In `m10` and `m14` the only periodic hello of the old board inside the window was sent (+33 to +34 s) and not received by the new board.
- The old board knows the new one in 2.5 to 4.8 s in all 16 meetings (the new board's first hello).
- Cost of the reply: one more hello per meeting (signature 111.3 ms on the sender, verification 173 to 184 ms on the receiver), no LoRa airtime. The reply is refused by the 30 s guard when the other board has just sent (intended).
- Hello delivery: the old board sent 25 hellos (24 received), the new one 32 (32 received); about 2 real losses out of 57 broadcast hellos, both from the old to the new board, no cause seen. **Loss rate not established.** An ESP-NOW broadcast hello has neither acknowledgement nor retry.
- The meeting reply is already part of the production build; the test builds only add the order to switch it off and the journal events.
- Limits: two boards only (no case with several neighbours), fixed roles (old/new), 8 meetings per condition, boards a few centimetres apart.

### Tools added in this part (`tools/`)

`analyse-balayage-recepteur.py` (receiver scans against lost frames; option `--suffixe board` to read the anonymised journals), `analyse-collisions-balayage.py` (scan end against the other board's start, for collisions),
`analyse-rencontres.py` (meetings), and the current `lib_journal_radio.py`, `journal-radio.py`, `analyse-journal-radio.py` (they know the CAD and hello events; these replace the copies of the previous folder).
The text outputs of the tools are in French (the tools are, our apologies).

## Runs

- `f1-saturation-17B-mediumfast-default-window` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, no pause; test build v7 at its default setting (contention window +2 bits for data frames, no setting order sent) - 61+61 frames, 70 strict conflicts, 1 collision(s).
- `f2-saturation-17B-mediumfast-default-window` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, no pause; test build v7 at its default setting (contention window +2 bits for data frames, no setting order sent) - 61+61 frames, 61 strict conflicts, 0 collision(s).
- `f3-saturation-17B-mediumfast-default-window` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, no pause; test build v7 at its default setting (contention window +2 bits for data frames, no setting order sent) - 61+61 frames, 57 strict conflicts, 1 collision(s).
- `g1-duplex-2KB-window-plus2-bits-longfast` (LONG_FAST): both boards send a 2,048-byte file to each other at the same time, contention window +2 bits for data frames - 17+17 frames, 0 strict conflicts, 0 collision(s).
- `g2-duplex-2KB-window-plus0-bits-longfast` (LONG_FAST): both boards send a 2,048-byte file to each other at the same time, contention window +0 bits for data frames - 17+17 frames, 0 strict conflicts, 0 collision(s).
- `g3-duplex-2KB-window-plus2-bits-longfast` (LONG_FAST): both boards send a 2,048-byte file to each other at the same time, contention window +2 bits for data frames (started 14 s after the end of the previous run instead of 10 min or more: a script error on our side; the run itself is valid) - 17+17 frames, 0 strict conflicts, 0 collision(s).
- `g4-duplex-2KB-window-plus0-bits-longfast` (LONG_FAST): both boards send a 2,048-byte file to each other at the same time, contention window +0 bits for data frames - 17+17 frames, 0 strict conflicts, 0 collision(s).
- `g5-duplex-2KB-window-plus2-bits-longfast` (LONG_FAST): both boards send a 2,048-byte file to each other at the same time, contention window +2 bits for data frames - 17+17 frames, 0 strict conflicts, 0 collision(s).
- `g6-duplex-2KB-window-plus0-bits-longfast` (LONG_FAST): both boards send a 2,048-byte file to each other at the same time, contention window +0 bits for data frames - 17+17 frames, 0 strict conflicts, 0 collision(s).
- `h1-priority-on-deep-queue-longfast` (LONG_FAST): control-frame priority ON (production setting), board 2 has a 12-frame burst of 219 B in its queue, board 1 sends a 1,024-byte file 42 s later - 8+16 frames, 0 strict conflicts, 0 collision(s).
- `h2-priority-off-deep-queue-longfast` (LONG_FAST): same without control-frame priority on board 2 (test option), 12-frame burst ahead of its ready frame - 11+21 frames, 0 strict conflicts, 0 collision(s).
- `h3-priority-on-deep-queue-longfast` (LONG_FAST): repeat of h1 (priority ON) - 10+18 frames, 1 strict conflicts, 0 collision(s).
- `h4-priority-off-deep-queue-longfast` (LONG_FAST): repeat of h2 (priority OFF) - 10+19 frames, 0 strict conflicts, 0 collision(s).
- `i1-saturation-17B-mediumfast-window-plus0-bits-cad` (MEDIUM_FAST): symmetric saturation, 80 frames of 17 B per board, no pause, contention window +0 bits for data frames; test build v8b with CAD scan events - 81+81 frames, 138 strict conflicts, 6 collision(s).
- `i2-saturation-17B-mediumfast-window-plus2-bits-cad` (MEDIUM_FAST): symmetric saturation, 80 frames of 17 B per board, no pause, contention window +2 bits for data frames; test build v8b with CAD scan events - 81+81 frames, 72 strict conflicts, 1 collision(s).
- `i3-saturation-17B-mediumfast-window-plus0-bits-cad` (MEDIUM_FAST): symmetric saturation, 80 frames of 17 B per board, no pause, contention window +0 bits for data frames; test build v8b with CAD scan events - 81+81 frames, 148 strict conflicts, 7 collision(s).
- `i4-saturation-17B-mediumfast-window-plus2-bits-cad` (MEDIUM_FAST): symmetric saturation, 80 frames of 17 B per board, no pause, contention window +2 bits for data frames; test build v8b with CAD scan events - 81+81 frames, 79 strict conflicts, 3 collision(s).
- `meetings/`: the 16 meetings of part M (journals, orders with the random waits, one analysis text each, `meetings.json`).
- `scan-analysis/`: scan analyses redone on the published journals.

## Limits and what is not shown

- Two boards side by side (no propagation loss, no hidden node); two to three runs per setting; the saturated runs are a worst case. Board 2 always started about 2 s after board 1, so we cannot tell whether its larger cost
  comes from its role in the exchange or from the board itself.
- **Only two Heltec V4 boards were used.** The other boards we compile for (T-Beam S3, T3-S3, T-Beam, T-Echo, T-Deck, Raspberry Pi) have never been tested by us. Some carry an SX127x chip whose channel scan is shorter (about 2.25 symbols) and has no direct hand-over to reception: our collision and scan figures come from an SX1262 with the Heltec V4 antenna circuit and do not transpose as they are.
- **No relay chain and no hidden node were measured on hardware.** Our frames are sent with `hop_limit` 0, so ordinary Meshtastic nodes do not repeat them; the relays of our protocol are our own stations, each sending a new local packet at every hop.
  Our simulation bench covers the queue and protocol logic, but it has no channel scan and no contention window, so it cannot predict collisions or hidden-node behaviour, and it is built from the same assumptions as our real tests: anything it suggests there is an extrapolation, not a measurement.
  The station code has never run in the firmware on real hardware.
- The USB-buffer positive control did not show a loss at 4,096 bytes (part U): the run cannot show what the buffer prevents.
- The meeting hello is measured on two boards only (part M); the hello loss rate of ESP-NOW broadcast is not established (about 2 in 57).
- Scans: the threshold of about 6.5 symbols rests on 7 lost frames out of 218 at SF9; the link between a late scan and a lost frame is observed in all runs, the mechanism is our reading of the code, not an experiment that changes it.
  One LONG_FAST loss (scans after the end of the preamble) and the excess of zero draws at +0 bit remain unexplained.
- Not measured: the effect of the +2 bit window on the periodic background packets of a board (position, node info, telemetry).
- The production figures (P1, P2, P2bis) are the values printed by our transfer tool, not independent radio measurements.
- Please tell us what looks wrong.
