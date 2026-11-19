# Real-hardware results on two Heltec V4 (18-19 November 2026)

Raw radio journals, analysis scripts and the analyses of every run quoted in
[discussion #12338](https://github.com/meshtastic/firmware/discussions/12338) (reply of 19 Nov 2026). License GPL-3.0.
Copyright (C) 2026 SoCodeIA and Vincent PERRIN.

## Setup

- Two Heltec V4 boards a few centimetres apart (no propagation loss, no hidden node), EU_868, ESP-NOW off, LoRa only, presets LONG_FAST or MEDIUM_FAST.
- Our protocol over `PRIVATE_APP` direct messages, no `want_ack`, `hop_limit` 0; stress runs use a test mode where each board sends numbered packets itself.
- A test build of our firmware fork (not published here) records what the radio does, with the microsecond clock of the chip, in two memory rings that are read
  back over USB **after** each run (nothing is printed while the radio works): when a packet enters the TX queue, every deferral of a transmission and its cause,
  TX start (with the airtime computed by the firmware), TX end and RX end from the radio interrupt, and every packet read out of the radio.

## Journal format (`journals/*.json`)

Top level: `format` (1), `boitier` (anonymised: `board-1`, `board-2`), `relu_le`, `entete` (SF, CR, bandwidth, preamble, region, preset, ring sizes, clock at read-out), `anneaux` with
two lists, `logiciel` (software events) and `isr` (interrupt time stamps). A record is `{type, info, x, id, t, aux}`:

- `t`: microseconds of the board clock (32 bits, wraps every 71 min; the analysis extends it with the clock read at the end). The two boards' clocks are **not** synchronised.
- `id`: the Meshtastic packet id, the same on the sending and the receiving board: it links the two journals.
- `type` 1 ENFILE (queued, `x` = queue length), 2 ATTENTE (a transmission is postponed, `info` 1 = radio receiving, 2 = CAD found the channel busy, 4 = a module deferred,
  5 = own transmission in progress), 3 TX_DEBUT (`x` = bytes on the air, `aux` = airtime computed by the firmware in microseconds), 4 TX_FIN (`aux` = number of the
  matching interrupt), 5 RX (`info` 0 = good, `0x80 | code` = error; `x` = bytes), 6 REGLAGE (test setting: `info` = letter, `x` = value),
  16 ISR_TX and 17 ISR_RX (interrupt time stamps, `aux` = sequence number, `info` bit 0 = seen by polling).

## How to read a run

    python3 tools/analyse-journal-radio.py journals/<run>-board1.json journals/<run>-board2.json
    python3 tools/analyse-conflits.py      journals/<run>-board1.json journals/<run>-board2.json

The first script aligns the two clocks on the packets both boards saw (offset + drift, both directions), compares measured TX duration with the Semtech formula,
and classifies every lost frame (the other board was transmitting / received with an error / no cause seen). The second finds every "strict conflict" (both boards
start a transmission within one second after the end of the same frame) and the collisions among them, with the start gap in microseconds. The text printed by the
scripts is in French; the numbers are what matters. `analysis/` and `conflicts/` hold their output for every run.

## Runs

- `a0-4KB-longfast` (LONG_FAST): 4 KB photo, protocol pace (first real run with the radio journal) - 24+3 frames, 0 strict conflicts, 0 collision(s).
- `a1-7.5KB-longfast` (LONG_FAST): 7.5 KB transfer, protocol pace - 41+4 frames, 0 strict conflicts, 0 collision(s).
- `a2-simultaneous-bursts-longfast` (LONG_FAST): worst case: both boards send a burst at the same time (10 and 6 frames of 219 B, no pause) - 11+7 frames, 0 strict conflicts, 0 collision(s).
- `b4-7.5KB-longfast-v5` (LONG_FAST): 7.5 KB transfer, protocol pace, firmware with control-frame priority - 41+4 frames, 0 strict conflicts, 0 collision(s).
- `b5-7.5KB-longfast-cw2` (LONG_FAST): 7.5 KB transfer, protocol pace, contention window +2 bits for data frames - 41+4 frames, 0 strict conflicts, 0 collision(s).
- `b6-30KB-mediumfast` (MEDIUM_FAST): 30,720 B transfer, protocol pace - 153+7 frames, 1 strict conflicts, 0 collision(s).
- `c1a-priority-test-collision` (LONG_FAST): priority test, first attempt: a real collision (start gap 1.44 ms) - 9+12 frames, 3 strict conflicts, 1 collision(s).
- `c1b-priority-on` (LONG_FAST): ready-to-receive frame with control priority, 4 data frames ahead of it - 7+12 frames, 1 strict conflicts, 0 collision(s).
- `c1c-priority-off` (LONG_FAST): same without control priority, 1 data frame ahead - 8+12 frames, 0 strict conflicts, 0 collision(s).
- `c1d-priority-test-collision` (LONG_FAST): priority test: a second real collision (start gap 7.8 ms) - 9+16 frames, 2 strict conflicts, 1 collision(s).
- `c1e-priority-on-deep-queue` (LONG_FAST): priority on, 12-frame burst in the queue: ready frame left after 2.2 s with 11 frames ahead - 10+18 frames, 4 strict conflicts, 2 collision(s).
- `c1f-priority-off-collision` (LONG_FAST): priority off, attempt hit by a collision (start gap 8.5 ms) - 9+17 frames, 1 strict conflicts, 1 collision(s).
- `c1g-priority-off-deep-queue` (LONG_FAST): priority off, 12-frame burst: ready frame left after 15.6 s with 7 frames ahead - 9+17 frames, 1 strict conflicts, 0 collision(s).
- `d1a-saturation-17B-longfast` (LONG_FAST): symmetric saturation, 60 frames of 17 B per board, no pause - 61+61 frames, 18 strict conflicts, 2 collision(s).
- `d1b-saturation-17B-longfast` (LONG_FAST): symmetric saturation, 60 frames of 17 B per board, no pause - 61+60 frames, 15 strict conflicts, 1 collision(s).
- `d1c-saturation-17B-longfast` (LONG_FAST): symmetric saturation, 60 frames of 17 B per board, no pause - 60+60 frames, 21 strict conflicts, 3 collision(s).
- `d2-saturation-219B-longfast` (LONG_FAST): symmetric saturation, 15 frames of 219 B per board, no pause - 16+16 frames, 1 strict conflicts, 1 collision(s).
- `d3-saturation-17B-mediumfast` (MEDIUM_FAST): symmetric saturation, 150 frames of 17 B per board, no pause - 151+151 frames, 232 strict conflicts, 10 collision(s).
- `e01-window-plus0-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +0 bit(s) for data frames - 61+61 frames, 102 strict conflicts, 9 collision(s).
- `e02-window-plus0-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +0 bit(s) for data frames - 61+61 frames, 113 strict conflicts, 10 collision(s).
- `e03-window-plus0-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +0 bit(s) for data frames - 61+61 frames, 99 strict conflicts, 10 collision(s).
- `e11-window-plus1-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +1 bit(s) for data frames - 61+61 frames, 95 strict conflicts, 7 collision(s).
- `e12-window-plus1-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +1 bit(s) for data frames - 61+61 frames, 100 strict conflicts, 5 collision(s).
- `e13-window-plus1-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +1 bit(s) for data frames - 61+61 frames, 91 strict conflicts, 4 collision(s).
- `e21-window-plus2-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +2 bit(s) for data frames - 61+61 frames, 69 strict conflicts, 0 collision(s).
- `e22-window-plus2-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +2 bit(s) for data frames - 61+61 frames, 55 strict conflicts, 3 collision(s).
- `e23-window-plus2-bits-mediumfast` (MEDIUM_FAST): symmetric saturation, 60 frames of 17 B per board, contention window +2 bit(s) for data frames - 61+61 frames, 56 strict conflicts, 1 collision(s).

## What the runs show (all numbers from the files above)

- Measured airtime equals the Semtech formula to 0.00 % over 41 to 153 frames per run (for example 94,001 ms measured against 93,998 ms computed for 30 KB in MEDIUM_FAST).
- At the pace of the protocol (the sender is silent for 3 d after a frame of duration d) nothing was lost: 4 KB, 7.5 KB (three runs), 30 KB.
- Saturation: collisions need both boards to wait for the end of the same frame and then draw the same slot of the random backoff; start gaps of the colliding frames were
  1.4 to 9.3 ms in LONG_FAST and 0.1 to 5.3 ms in MEDIUM_FAST, never between 10 and 300 ms.
- Widening the contention window of bulk (BACKGROUND) frames by 0, 1, 2 bits (MEDIUM_FAST, 3 x 122 frames each): collisions 29, 16, 4.
  Runs lasted 29 s, 38 s, 55 s on average in this saturated test; the same 7.5 KB LONG_FAST transfer took 325 s with and without the extra bits (`b4` and `b5`).
- Control frames (ready, summary, question) sent with priority RESPONSE instead of BACKGROUND: a ready frame left after 2.2 s with 11 data frames ahead (`c1e`), 15.6 s with 7 ahead without it (`c1g`).

## Limits

Two boards only, side by side; a handful of repetitions per case; saturated runs are a worst case; no relay chain tested; the firmware changes are in our fork. Please tell us what looks wrong.
