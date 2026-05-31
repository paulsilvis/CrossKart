# CLAUDE.md — Cross-Kart Telemetry Project

## What This Project Is

A hobbyist-but-serious telemetry and replay system for an off-road racing kart,
built by Paul and Gary. It logs sensor data during runs and replays it with
visually compelling animation. The experience goal: "That is really cool."

This is a fun engineering project. It should stay that way.

---

## Current Status

**Phase:** Architecture and design. Hardware not yet finalized.
Active work is on:
- Flask+canvas viewer (server.py + viewer/index.html) — replaces Streamlit for main playback
- Synthetic data generation (`make_synth_session.py`)
- Browser-based replay viewer
- Hardware selection

Known issues in the viewer:
- NaN rendering artifacts

---

## Project Structure

> Update this section as the codebase grows.

```
/                          # repo root
├── CLAUDE.md              # this file
├── firmware/              # ESP32 firmware (C/C++ / Arduino / IDF)
├── logger/                # host-side session tools
│   └── make_synth_session.py
├── viewer/                # browser-based replay UI
└── docs/                  # design notes, diagrams
```

---

## How To Run Things

### On Windows (Gary's path)

**One-time setup:**
1. Install Python 3.10+ from https://www.python.org/downloads/
   — check **"Add Python to PATH"** during install.
2. Install GitHub Desktop from https://desktop.github.com/
3. In GitHub Desktop: **File → Clone Repository** → paste the repo URL.

**Every time:**
- Double-click **`launch.pyw`** in the project folder.
- First launch only: a dialog says "setting up" — wait ~1 minute.
- The viewer opens in your browser. Drag in a session CSV to begin.

**Getting updates:**
- Open GitHub Desktop → click **Fetch origin** → **Pull**.
- Then double-click `launch.pyw` as usual.

---

### On Linux / Mac (Paul's path)

```bash
# One-time: create virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Generate a synthetic session
python logger/make_synth_session.py

# Launch the viewer
streamlit run viewer/view_session.py
```

---

## Hardware (Decided or Strongly Leaning)

| Component     | Choice              | Notes                              |
|---------------|---------------------|------------------------------------|
| MCU           | ESP32 (WROOM or S3) | Wi-Fi, adequate perf, cheap        |
| GNSS          | u-blox M10N         | Modern, good update rate, no RTK   |
| IMU           | TBD (BNO085 likely) | Want fusion output eventually      |
| Storage       | MicroSD via SPI     | Session files, easy extraction     |
| Power         | 12V → buck → 3.3V   | From kart electrical system        |

RTK GPS is intentionally deferred. It adds complexity with diminishing returns
for this use case.

---

## Data Format

Sessions are self-contained files. Current preference: start with CSV or JSON
(human-readable), move to binary only if performance demands it.

Each session contains:
- Timestamped telemetry (GPS pos, speed, IMU accel, gyro)
- Session metadata
- Optional: manual event markers, audio

---

## Engineering Principles

**Follow these. Do not drift from them.**

1. **Reliability first.** The logger must survive vibration, power glitches, and
   noisy 12V systems. Corrupt logs are the worst outcome.

2. **Simplicity.** One clear way to do each thing. No premature abstraction.
   No framework bloat.

3. **Readable code.** Explicit over clever. If it needs a comment to understand,
   write the comment. If it can be restructured to be obvious, restructure it.

4. **Test everything incrementally.** Each layer gets tests or mockups before
   the next layer is built. Synthetic data exists precisely for this.

5. **Layer by layer.** Do not build layer N+1 until layer N works and is tested.

6. **Not a hydra.** When a new idea would add a head to the snake, write it down
   for later. Don't build it now.

---

## Development Approach

- Iterative and experimental — trying ideas is encouraged
- Synthetic data (`make_synth_session.py`) is the primary dev/test tool
   until real hardware exists
- Visualization quality matters — this is half the point of the project
- Each system (firmware, logger, viewer) should be independently testable

---

## Out of Scope for V1

- RTK GPS
- Cloud connectivity
- Real-time telemetry dashboard
- Multi-kart support
- AI event detection

These are written down. They will not be forgotten. They are not happening yet.

---

## People

- **Paul** — builder, lead developer
- **Gary** — co-builder, hardware contributor, audio integration advocate
