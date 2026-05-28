# Session File Format  (schema v1)

## Overview

Each session is a single CSV file. Every row is one IMU sample.
The file is self-contained — no external schema file needed.

### Naming convention
```
session_YYYYMMDD_HHMMSS.csv
```

---

## Columns

| Column  | Type    | Unit      | Description |
|---------|---------|-----------|-------------|
| `t`     | float64 | seconds   | Time from session start.  Monotonically increasing. |
| `ax`    | float64 | m/s²      | Longitudinal acceleration. +forward. Gravity NOT included. |
| `ay`    | float64 | m/s²      | Lateral acceleration. +left. Gravity NOT included. |
| `az`    | float64 | m/s²      | Vertical acceleration. +up. **Gravity IS included** (~9.81 at rest). |
| `gx`    | float64 | rad/s     | Roll rate. |
| `gy`    | float64 | rad/s     | Pitch rate. |
| `gz`    | float64 | rad/s     | Yaw rate. +left-turn positive. |
| `lat`   | float64 | deg       | GPS latitude, WGS-84. |
| `lon`   | float64 | deg       | GPS longitude, WGS-84. |
| `spd`   | float64 | **m/s**   | Ground speed from GPS. Convert to mph: × 2.236936. |
| `hdg`   | float64 | deg       | Heading, degrees. 0 = North, clockwise. |
| `roll`  | float64 | deg       | Roll angle. +right-side-down. |
| `pitch` | float64 | deg       | Pitch angle. +nose-up. |
| `yaw`   | float64 | deg       | Yaw angle, -180..+180. 0 = initial heading. |
| `qw`    | float64 | —         | Quaternion scalar (body frame, ZYX convention). |
| `qx`    | float64 | —         | Quaternion x. |
| `qy`    | float64 | —         | Quaternion y. |
| `qz`    | float64 | —         | Quaternion z. |
| `sat`   | int     | —         | GPS satellites in view. |
| `hdop`  | float64 | —         | Horizontal dilution of precision. Lower = better. |
| `marker`| str     | —         | Event label or empty string. See below. |

Total: 21 columns.

---

## Sample Rate

- IMU channels (`t, ax, ay, az, gx, gy, gz, roll, pitch, yaw, qw-qz`): **50 Hz**
- GPS channels (`lat, lon, spd, hdg, sat, hdop`): **10 Hz**, held constant between updates

A new GPS fix is reflected every 5th row.  Viewer code should handle
the staircase pattern in lat/lon without treating held values as jumps.

---

## Marker Events

The `marker` column is empty for the vast majority of rows.
When an event is recorded, exactly one row carries the label.

| Label   | Meaning |
|---------|---------|
| `JUMP`  | Takeoff; kart goes airborne. Landing ~0.5 s later. |
| `BUMP`  | Sharp vertical impulse (rock, rut, kerb). |
| `BRAKE` | Significant braking zone begins. |
| `SLIDE` | Rear-end slide or yaw disturbance. |

Viewer should scan the marker column for display on the timeline and map.

---

## Axis Convention (IMU Frame)

```
         +Z (up)
          |
          |
          +------> +X (forward)
         /
        /
      +Y (left)
```

The IMU is mounted with:
- **+X** pointing toward the front of the kart
- **+Y** pointing toward the driver's left
- **+Z** pointing up

This must match the physical mounting of the BNO085.
Document any deviation in the firmware header.

---

## Notes

- `az` includes gravity (+9.81 m/s² at rest on level ground).
  To get pure vertical motion, subtract G0 = 9.80665.

- Quaternion convention: **unit quaternion, ZYX intrinsic rotation** (yaw→pitch→roll).
  This matches BNO085 "rotation vector" report output.

- Future firmware will produce this exact schema.
  The synthetic generator (`tools/make_synth_session.py`) is the reference implementation.
