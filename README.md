# Reliable transfer of messages and small photos over Meshtastic

A transfer protocol for messages too long for one packet and small photos of a few KB over Meshtastic LoRa, running in the client (app or
computer). **No firmware change is needed.**

Authors: SoCodeIA and Vincent PERRIN. License: GNU General Public License version 3 ([`LICENSE`](LICENSE)), like
the Meshtastic firmware. Status: draft for discussion with the Meshtastic team, November 2026.

## In short

- `PRIVATE_APP` direct messages without `want_ack`, `BACKGROUND` priority.
- Chunks of up to 215 bytes in groups of 8, with 0 to 2 RAID-6-style parity chunks per group, adapted to the loss
  rate; a small content is cut into equal chunks (450 bytes: 3 × 150, not 215 + 215 + 20).
- One summary per window of 4 groups instead of one ack per packet; only missing chunks are resent.
- Exact resume after an interruption, even from another sender (CRC32 fingerprint).
- Its own airtime budget: at most 5 % of the sliding hour, half of the EU duty cycle, and a steady 25 % pace on the
  channel.

Full specification: [`SPEC.md`](SPEC.md).

## Results so far (simulated radio)

On a bench running the real Meshtastic 2.8.3 firmware built for Linux, with a simulated radio (per-link loss and
LoRa airtime), chain A - R - B, LONG_FAST, 4 KB, 5 runs per case:
- 10 % loss: **5 complete files out of 5** (109 s of airtime), against 2 out of 5 by splitting the file into acked
  messages (125 s);
- 20 % loss: **5 out of 5** (127 s), against 0 out of 5 (133 s).

**Not yet tested on real radios.** Two Heltec V4 boards are on order; results will be added here.

## Contents

- [`prototype/`](prototype/): reference implementation in Python (`protocole.py`, `raid6.py`), an in-memory
  simulation of a lossy link (`simulation.py`) and tests.
- [`cpp/`](cpp/): C++ port of the same protocol, written for the Meshtastic firmware, and a test that replays the
  Python reference frame by frame (same bytes, same times, same budget results, same parity).
- [`outils/`](outils/): LoRa airtime per preset (`temps-antenne.py`, from `src/mesh/MeshRadio.h:216` and Semtech's
  formula) and the generator of the C++ test vectors (`vecteurs-protocole.py`).

Identifiers and code comments are in French; this README and the specification are in English. Some comments cite
our study notes (`docs/NN`, `essais/…`), which are not published here; what the protocol relies on is in
[`SPEC.md`](SPEC.md).

## Running the tests

```sh
python3 -m unittest discover prototype/tests          # Python reference (11 tests)
python3 prototype/simulation.py                       # simulation: acked messages vs. this protocol
python3 outils/vecteurs-protocole.py                  # regenerate cpp/test/vecteurs.h from the Python reference
g++ -std=c++17 -Icpp cpp/Protocole.cpp cpp/Raid6.cpp cpp/test/test_main.cpp -o test_cpp && ./test_cpp
```

The C++ test runs with a plain compiler through a few Unity-style assertions (`cpp/test/unity_mini.h`); in the
firmware tree the same test runs under PlatformIO.

## Related work (not in this repository)

The same authors are also working, on a simulated bench for now, on ESP-NOW next to LoRa between nearby ESP32
nodes, and on relay stations that store and forward whole contents inside the firmware of a Heltec V4. Those will
be shared once tested on real hardware.
