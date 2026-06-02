# CrossKart Firmware — Phase 1: IMU Verification

One chip at a time. This phase gets the BNO085 talking and verified
before any other hardware is connected.

## Hardware needed
- ESP32-WROOM-32U (BAKODELOP devkit)
- Adafruit BNO085 breakout (#4754)
- 4× jumper wires
- USB cable to PC

## Wiring

| BNO085 | ESP32 | Note |
|--------|-------|------|
| VIN    | 3V3   | NOT 5V |
| GND    | GND   |      |
| SDA    | GPIO 21 | I2C |
| SCL    | GPIO 22 | I2C |
| PS0    | GND   | REQUIRED — selects I2C mode |
| PS1    | GND   | REQUIRED — selects I2C mode |
| RST    | —     | leave unconnected |
| INT    | —     | leave unconnected for now |

**PS0 and PS1 must both be tied to GND.** Without this the BNO085
defaults to SPI and will not respond on I2C.

## First-time setup

```bash
cd firmware_imu
pip install pyserial matplotlib numpy   # host-side tools only
```

PlatformIO will handle all firmware dependencies automatically on first build.

## Build & flash

```bash
make build    # compile only
make flash    # compile + upload
make fm       # flash + open serial monitor (most useful during bring-up)
```

## What you should see in the serial monitor

```
# CrossKart IMU — Phase 1 verification
# BNO085 on I2C, 10 Hz
# Columns: ms,qi,qj,qk,qr,ax,ay,az,gx,gy,gz,cal_a,cal_g,cal_m
# BNO085 found OK
# Firmware version: 3.7.4
# Reports enabled — streaming:
1234,0.00012,-0.00034,0.70711,0.70711,0.012,-0.005,0.001,0.0002,-0.0001,0.0003,0,0,0
...
```

If you see `BNO085 not found` repeated — check PS0/PS1 wiring first.

## Live visualizer (run on host PC, separate terminal)

```bash
make viz
# or explicitly:
python3 tools/visualizer.py        # auto-detect port
python3 tools/visualizer.py COM7   # Windows explicit
python3 tools/visualizer.py /dev/ttyUSB0  # Linux explicit
```

Shows:
- 3D kart model rotating in real time with the sensor
- Calibration status bars (Accel / Gyro / Mag) — watch these climb to HIGH
- Linear acceleration strip chart (X/Y/Z)
- G-force magnitude strip chart

## Calibration

The BNO085 self-calibrates in the background. Calibration status 0–3:
- 0 = UNRELIABLE (just powered on)
- 1 = LOW
- 2 = MED
- 3 = HIGH ← target

To speed up calibration:
- **Gyro**: just leave it still for ~5 seconds
- **Accel**: tilt to 6 different orientations (face up, face down, each side)
- **Mag**: figure-8 motions in the air

The BNO085 stores calibration in its own flash and reloads it on power-up,
so you only need to do this once (or after firmware changes).

## Expected numbers when sitting still

| Field | Expected |
|-------|----------|
| qi, qj, qk | near 0 |
| qr | near ±1 |
| ax, ay, az | near 0 (gravity removed) |
| gx, gy, gz | near 0 |
| cal_a, cal_g, cal_m | 0 initially → 3 after calibration |
