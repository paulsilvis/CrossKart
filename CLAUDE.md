# Cross-Kart Telemetry Project — CLAUDE.md

## Overview

This project is a hobbyist-but-serious telemetry and visualization system for a cross-kart (off-road racing kart) developed by Paul and his brother Gary.

The goal is not professional motorsport telemetry, but a robust, visually impressive system capable of:

* Logging telemetry during kart runs
* Recording GPS position, speed, acceleration, and rotation
* Allowing manual event markers
* Replaying runs with a highly visual animated playback system
* Supporting "beer-night replay analysis" and experimentation
* Providing a foundation for future expansion

The project emphasizes:

* Practical engineering
* Reliability
* Clear architecture
* Visually compelling playback
* Simple hardware
* Offline analysis and experimentation

---

# Core Goals

## Telemetry Capture

The system should record:

* GPS position
* GPS speed
* IMU acceleration
* IMU angular rotation
* Timestamps
* Optional manual event markers
* Optional audio recording (engine sound)

Target environment:

* Cross-kart
* Up to ~50 MPH
* Typical speeds 20–30 MPH
* Rough grass/dirt environment
* Significant vibration

---

# Design Philosophy

## Priorities

1. Reliability
2. Simplicity
3. Clear architecture
4. Cool playback visuals
5. Expandability
6. Robust logging
7. Fun experimentation

## Non-goals

* Professional motorsports telemetry
* RTK-grade positioning (for V1)
* Ultra-tight real-time constraints
* Overengineered abstraction
* Cloud dependence

---

# Planned Hardware

## Microcontroller

ESP32 family.

Candidates considered:

* ESP32-WROOM
* ESP32 DevKitC
* ESP32 with external antenna
* ESP32-CAM variants

Reasons:

* Cheap
* Excellent ecosystem
* Wi-Fi support
* Adequate performance
* Good storage support
* Familiarity

---

## GPS / GNSS

Candidates discussed:

* u-blox NEO-6M
* u-blox M9N
* u-blox M10N

Current leaning:

* M10N

Reasoning:

* Modern
* Better sensitivity
* Better update rates
* Good price/performance

RTK is intentionally deferred for V1 because:

* Complexity
* Infrastructure requirements
* Diminishing returns for intended use

---

## IMU Options

Discussed:

* MPU6050 / GY-521
* ADXL345
* BNO055
* BNO085/BNO086

Current direction:

* Likely a fused-orientation IMU eventually
* Simpler IMU acceptable for early prototypes

Data desired:

* 3-axis acceleration
* 3-axis gyro
* Orientation estimation later

---

## Storage

Primary logging target:

* MicroSD card

Possible interfaces:

* SPI SD modules
* SDIO-capable modules later

Requirements:

* Robust write behavior
* Session-oriented files
* Easy extraction and replay

---

## Power

Vehicle 12V system.

Expected:

* Buck converter to 5V/3.3V
* Noise filtering
* Vibration-resistant wiring

---

## Enclosure

Goals:

* Rugged
* IP-rated
* Shock resistant
* Serviceable

Ideas discussed:

* Clear lid
* Internal mounting grid
* Foam isolation layers
* Roll-cage-mounted GNSS antenna

---

# Data Logging

## Session-Oriented Logging

Each run should become a self-contained session.

Likely contents:

* Timestamped telemetry stream
* Metadata
* Optional markers
* Optional audio

Potential formats:

* CSV
* JSON
* Binary later if needed

Initial preference:

* Human-readable/simple formats

---

# Visualization System

## Major Goal

The visualization/playback system is considered one of the most important parts of the project.

Desired features:

* Animated replay
* GPS track display
* Timeline scrubber
* Speed display
* G-force visualization
* Orientation display
* Optional lap overlays
* Optional trail overlays
* Marker playback
* "Ridiculously cool" presentation

The user experience matters more than racing-grade analytics.

---

## Planned Visual Concepts

### 3D Wireframe Kart

Possible animated representation:

* Rotating wireframe kart
* Tilt based on IMU data
* Suspension-like visual motion
* Velocity vectors
* Acceleration vectors

### Track Replay

* Draw GPS path
* Show moving kart marker
* Replay synchronized telemetry
* Overlay multiple laps eventually

### Audio Integration

Gary strongly suggested synchronized audio playback:

* Engine sound recorded with run
* Synchronized with replay
* Engine pitch provides intuitive feedback

This is considered a high-value future enhancement.

---

# Synthetic Data System

A synthetic data generator exists to:

* Test visualization
* Develop playback UI
* Simulate tracks
* Debug rendering

Example:

* `make_synth_session.py`

Capabilities discussed:

* Twisty tracks
* Aggression parameter
* Seeded reproducibility
* Replay debugging

Issues encountered:

* NaN rendering artifacts
* Trail endpoint issues
* Playback synchronization bugs

---

# Viewer / Playback Architecture

The current direction is:

* Browser-based viewer
* Simple deployment
* Local/offline use
* Friendly for non-CLI users

Potential technologies:

* Python backend
* Streamlit prototype
* WebGL later
* Three.js possibilities
* Canvas/SVG rendering

The playback viewer is expected to evolve substantially.

---

# Networking / Data Transfer

Preferred workflow:

* Kart logs locally
* Wi-Fi offload when returning home/shop
* No cloud requirement

Possible transfer methods:

* Wi-Fi auto-upload
* Browser download
* SD card extraction fallback

---

# Engineering Style

The project strongly values:

* Clarity
* Simplicity
* Practicality
* Directness
* Minimal unnecessary abstraction

Code should:

* Be readable
* Be debuggable
* Avoid framework bloat
* Favor explicit behavior

---

# Development Philosophy

This is:

* Experimental
* Iterative
* Engineering-driven
* Visualization-heavy

The project intentionally encourages:

* Trying ideas
* Simulating data
* Incremental improvement
* Fun experimentation

The system should remain hackable and understandable.

---

# Future Possibilities

Potential future features:

* Multiple synchronized cameras
* Audio analysis
* Real-time telemetry display
* Live Wi-Fi dashboard
* Lap comparison
* Kalman filtering
* Terrain visualization
* AI-assisted event detection
* Multiple kart support
* RTK GPS later
* OLED or embedded dashboard
* Motion-triggered recording
* Telemetry export formats

---

# Important Constraints

## Reliability First

The logger must:

* Survive vibration
* Avoid corrupt logs
* Recover cleanly from power loss
* Tolerate noisy electrical systems

---

## Simplicity Matters

Avoid:

* Overengineering
* Premature abstraction
* Unnecessary dependencies
* Excessive architectural complexity

---

# Current Status

Current phase:

* Architecture exploration
* Hardware selection
* Visualization prototyping
* Synthetic data generation
* Playback experimentation

The replay/viewer system is currently the most visually developed component.

---

# Intended Tone of the Project

This is fundamentally:

* A fun engineering project
* A visualization playground
* A telemetry experiment
* A shared hobby between brothers

The spirit of the project matters as much as the technical results.

The ideal result is something that:

* Works reliably
* Looks fantastic
* Is enjoyable to use
* Makes people say:
  "That is really cool." /Bob

