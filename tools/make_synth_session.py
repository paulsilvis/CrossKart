#!/usr/bin/env python3
"""
Cross-Kart Telemetry — Synthetic Session Generator
====================================================
Generates a physically plausible 50 Hz telemetry CSV for development
and viewer testing.  No hardware required.

Usage:
    python3 make_synth_session.py                              # defaults
    python3 make_synth_session.py --out data/run1.csv
    python3 make_synth_session.py --track twisty --aggression 0.8 --seed 42
    python3 make_synth_session.py --duration 120 --track oval --validate

Output CSV columns (schema v1):
    t        float   seconds from session start
    ax       float   m/s²  longitudinal accel  (+forward)
    ay       float   m/s²  lateral accel       (+left)
    az       float   m/s²  vertical accel      (+up, includes gravity ~9.81)
    gx       float   rad/s roll rate
    gy       float   rad/s pitch rate
    gz       float   rad/s yaw rate             (+left-turn positive)
    lat      float   decimal degrees
    lon      float   decimal degrees
    spd      float   m/s
    hdg      float   degrees, 0=North clockwise
    roll     float   degrees  (+right side down)
    pitch    float   degrees  (+nose up)
    yaw      float   degrees  (-180..+180, 0=initial heading)
    qw qx qy qz  float  unit quaternion (body frame, ZYX convention)
    sat      int     GPS satellites in view
    hdop     float   GPS horizontal dilution of precision
    marker   str     JUMP / BUMP / BRAKE / SLIDE / "" (empty = no event)
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


# ── Standard constants ────────────────────────────────────────────────────────
G0 = 9.80665  # m/s²

# ── Kart physical envelope ────────────────────────────────────────────────────
# These are realistic limits for a cross-kart at spirited play.
V_MAX_MPS        = 22.0          # ~49 mph absolute top
V_MIN_MPS        =  2.0          # kart always keeps moving
A_LON_MAX        =  1.0 * G0     # max forward accel  (~1 g, kart is light)
A_LON_MIN        = -2.0 * G0     # max braking        (~2 g, aggressive)
A_LAT_MAX        =  2.5 * G0     # max lateral        (~2.5 g, hard cornering)
AZ_AIRBORNE      =  0.3 * G0     # vertical accel during jump (near-weightless)
AZ_LANDING_MAX   = 10.0 * G0     # landing spike peak (~10 g, big jump)
AZ_BUMP_MAX      =  5.0 * G0     # bump spike peak    (~5 g)
YAW_RATE_MAX     =  2.5          # rad/s  (~143 deg/s, very tight spin)
ROLL_MAX_RAD     = math.radians(12.0)
PITCH_MAX_RAD    = math.radians(10.0)

# ── IMU noise model (BNO085 fused output + kart vibration floor) ──────────────
ACCEL_NOISE_STD   = 0.15    # m/s² RMS per sample at 50 Hz
GYRO_NOISE_STD    = 0.012   # rad/s RMS per sample
ACCEL_BIAS_INIT   = 0.07    # m/s² initial bias 1-sigma
GYRO_BIAS_INIT    = 0.003   # rad/s initial bias 1-sigma
ACCEL_BIAS_WANDER = 1.5e-4  # m/s² per sample random walk
GYRO_BIAS_WANDER  = 8e-6    # rad/s per sample random walk

# ── GPS noise model (u-blox M10, open sky, 10 Hz) ────────────────────────────
GPS_POS_NOISE_M   = 1.5     # m per fix, 1-sigma
GPS_WALK_STD_M    = 0.05    # m/sample slow position drift
HDOP_NOMINAL      = 0.90
HDOP_WANDER_STD   = 0.018
SAT_NOMINAL       = 14


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GenParams:
    duration_s:  float = 240.0
    imu_hz:      int   = 50
    gps_hz:      int   = 10
    track:       str   = "mixed"
    aggression:  float = 0.70    # 0..1
    seed:        int   = 1
    origin_lat:  float = 32.0809
    origin_lon:  float = -81.0912
    loop_m:      float = 520.0   # approximate track perimeter


@dataclass
class EventImpulse:
    """A single pre-scheduled event impulse affecting specific signal channels."""
    index:    int           # sample index
    label:    str           # JUMP / BUMP / BRAKE / SLIDE
    ax_delta: float = 0.0
    ay_delta: float = 0.0
    az_delta: float = 0.0
    duration: int   = 1     # samples the primary impulse lasts


# ── Geometry helpers ──────────────────────────────────────────────────────────

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def heading_from_dxdy(dx: float, dy: float) -> float:
    """North-clockwise heading in degrees from a (dx=east, dy=north) vector."""
    deg = math.degrees(math.atan2(dx, dy))
    return deg % 360.0


def meters_to_latlon(
    origin_lat: float, origin_lon: float, x_m: float, y_m: float
) -> Tuple[float, float]:
    """Equirectangular approximation — fine for small (<5 km) synthetic tracks."""
    cos_lat = math.cos(math.radians(origin_lat))
    return (
        origin_lat + y_m / 111_320.0,
        origin_lon + x_m / (111_320.0 * cos_lat),
    )


def euler_to_quat(roll_r: float, pitch_r: float, yaw_r: float) -> Tuple[float,float,float,float]:
    """Intrinsic ZYX (yaw→pitch→roll) Euler to unit quaternion."""
    cr, sr = math.cos(roll_r / 2),  math.sin(roll_r / 2)
    cp, sp = math.cos(pitch_r / 2), math.sin(pitch_r / 2)
    cy, sy = math.cos(yaw_r / 2),   math.sin(yaw_r / 2)
    return (
        cr * cp * cy + sr * sp * sy,   # qw
        sr * cp * cy - cr * sp * sy,   # qx
        cr * sp * cy + sr * cp * sy,   # qy
        cr * cp * sy - sr * sp * cy,   # qz
    )


# ── Track generation ──────────────────────────────────────────────────────────

def make_track_xy(
    track: str, n_pts: int, loop_m: float
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate (x, y) centerline points in metres around the origin.
    The track is a closed loop; the last point connects back to the first.
    """
    t = np.linspace(0.0, 2.0 * math.pi, n_pts, endpoint=False)
    r0 = loop_m / (2.0 * math.pi)

    if track == "oval":
        return r0 * 1.4 * np.cos(t), r0 * 0.7 * np.sin(t)

    if track == "twisty":
        r = r0 * (1.0 + 0.22 * np.sin(3 * t) + 0.14 * np.sin(7 * t + 0.7))
        x = r * np.cos(t) + 7.0 * np.sin(2 * t + 1.6)
        y = r * np.sin(t) + 5.5 * np.sin(4 * t - 0.3)
        return x, y

    if track == "hill":
        r = r0 * (1.0 + 0.14 * np.sin(2 * t) + 0.09 * np.sin(5 * t + 0.5))
        return r * np.cos(t) + 4.0 * np.sin(2 * t), r * np.sin(t) + 3.5 * np.sin(3 * t + 0.4)

    # "mixed" — default
    r = r0 * (1.0 + 0.20 * np.sin(3 * t) + 0.11 * np.sin(9 * t + 0.9))
    x = r * np.cos(t) + 6.5 * np.sin(2 * t + 0.3)
    y = r * np.sin(t) + 4.5 * np.sin(5 * t - 0.6)
    # one chicane bump
    x += 3.5 * np.exp(-((t - 2.8) ** 2) / 0.03) - 3.5 * np.exp(-((t - 3.1) ** 2) / 0.03)
    return x, y


def arc_length_table(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    Returns cumulative arc-length table s[0..N] where s[N] = total track length.
    Closing segment (last→first point) is included.
    """
    dx = np.diff(np.r_[x, x[0]])
    dy = np.diff(np.r_[y, y[0]])
    ds = np.sqrt(dx * dx + dy * dy)
    return np.r_[0.0, np.cumsum(ds)], float(ds.sum())


def sample_track_at(
    x: np.ndarray, y: np.ndarray, s_tbl: np.ndarray, s: float
) -> Tuple[float, float, float]:
    """
    Interpolate track position and heading at arc-length s (wraps around).
    Returns (x_m, y_m, heading_deg).
    """
    total = float(s_tbl[-1])
    s_mod = s % total
    n = len(x)
    i0 = int(clamp(int(np.searchsorted(s_tbl, s_mod, side="right")) - 1, 0, n - 1))
    i1 = (i0 + 1) % n
    s0, s1 = float(s_tbl[i0]), float(s_tbl[i0 + 1])
    frac = 0.0 if s1 <= s0 else (s_mod - s0) / (s1 - s0)
    xi = float(x[i0]) + frac * (float(x[i1]) - float(x[i0]))
    yi = float(y[i0]) + frac * (float(y[i1]) - float(y[i0]))
    hdg = heading_from_dxdy(float(x[i1]) - float(x[i0]), float(y[i1]) - float(y[i0]))
    return xi, yi, hdg


def track_curvature(
    x: np.ndarray, y: np.ndarray, s_tbl: np.ndarray, s: float
) -> float:
    """
    Estimate signed curvature kappa (1/m) at arc-length s using central difference.
    Positive = left turn.
    """
    probe = 2.5  # metres either side
    _, _, h_bk = sample_track_at(x, y, s_tbl, s - probe)
    _, _, h_fw = sample_track_at(x, y, s_tbl, s + probe)
    dh = h_fw - h_bk
    # unwrap heading difference
    while dh >  180.0: dh -= 360.0
    while dh < -180.0: dh += 360.0
    return math.radians(dh) / (2.0 * probe)


# ── Velocity model ────────────────────────────────────────────────────────────

def compute_target_speed(
    kappa_arr: np.ndarray, aggression: float
) -> np.ndarray:
    """
    Corner-speed model: reduce target speed proportional to curvature.
    v_target = v_straight / (1 + k_c * v_straight^2 * |kappa|)
    where k_c is chosen so lateral accel ≈ A_LAT_MAX at max cornering.
    """
    v_straight = 12.0 + 10.0 * aggression   # m/s  (~27–49 mph)
    # k_c: at full kappa usage, a_lat = v²·|kappa| = A_LAT_MAX
    # v_corner = sqrt(A_LAT_MAX / |kappa_typical|)
    # We use a soft cornering model:
    k_c = 1.0 / A_LAT_MAX   # guarantees a_lat ≤ A_LAT_MAX in steady-state
    v_target = v_straight / (1.0 + k_c * v_straight * v_straight * np.abs(kappa_arr))
    return np.clip(v_target, V_MIN_MPS, V_MAX_MPS)


def smooth_velocity(
    v_target: np.ndarray, aggression: float, rng: np.random.Generator
) -> np.ndarray:
    """
    First-order lag filter on target speed.
    tau controls how quickly the kart accelerates/brakes to follow target speed.
    Higher aggression → shorter time constant (more responsive driver).
    """
    tau_s = 1.8 - 0.8 * aggression   # seconds; 1.0 s (aggressive) to 1.8 s (easy)
    imu_hz = 50.0
    alpha = 1.0 / (tau_s * imu_hz)   # per-sample weight toward target

    v = np.empty_like(v_target)
    v[0] = float(v_target[0])
    for i in range(1, len(v_target)):
        v[i] = v[i - 1] + alpha * (float(v_target[i]) - v[i - 1])

    # tiny speed jitter (engine pulse, terrain micro-variation)
    v += rng.normal(0.0, 0.08, size=len(v))
    return np.clip(v, V_MIN_MPS, V_MAX_MPS)


# ── Event scheduling ──────────────────────────────────────────────────────────

def schedule_events(
    duration_s: float, aggression: float, rng: random.Random
) -> Dict[int, EventImpulse]:
    """
    Place event impulses at pseudo-random times with minimum spacing.
    Returns dict keyed by sample index.
    """
    imu_hz = 50

    n_jump  = int(1 + aggression * 4)
    n_bump  = int(5 + aggression * 15)
    n_brake = int(2 + aggression * 7)
    n_slide = int(1 + aggression * 5)

    def pick_indices(count: int, guard_s: float) -> List[int]:
        times: List[float] = []
        for _ in range(count * 30):          # max attempts
            if len(times) >= count:
                break
            tt = rng.uniform(5.0, duration_s - 8.0)
            if all(abs(tt - u) >= guard_s for u in times):
                times.append(tt)
        return [int(tt * imu_hz) for tt in sorted(times)]

    events: Dict[int, EventImpulse] = {}

    # JUMP: brief near-weightlessness, then hard landing spike
    # We mark the TAKEOFF index; the landing is encoded in duration.
    jump_duration_samples = int(0.50 * imu_hz)   # ~0.5 s airborne
    for idx in pick_indices(n_jump, 8.0):
        az_delta = AZ_AIRBORNE - G0              # net delta from baseline ~1g (so goes to 0.3g)
        events[idx] = EventImpulse(
            index=idx, label="JUMP",
            az_delta=az_delta,
            duration=jump_duration_samples,
        )

    # BUMP: sharp vertical spike, single sample
    for idx in pick_indices(n_bump, 1.5):
        if idx not in events:
            sign = rng.choice([-1, 1])
            events[idx] = EventImpulse(
                index=idx, label="BUMP",
                az_delta=sign * (3.0 + 2.0 * aggression) * G0,
                ax_delta=rng.uniform(-1.0, 1.0) * 0.5 * G0,
                duration=2,
            )

    # BRAKE: speed reduction (handled in velocity layer); marker only here
    for idx in pick_indices(n_brake, 6.0):
        if idx not in events:
            events[idx] = EventImpulse(index=idx, label="BRAKE", duration=1)

    # SLIDE: yaw disturbance (handled in yaw layer); marker only here
    for idx in pick_indices(n_slide, 6.0):
        if idx not in events:
            events[idx] = EventImpulse(index=idx, label="SLIDE", duration=1)

    return events


# ── Main generation ───────────────────────────────────────────────────────────

def generate(p: GenParams) -> pd.DataFrame:
    rng     = np.random.default_rng(p.seed)
    rng_py  = random.Random(p.seed)

    dt  = 1.0 / p.imu_hz
    n   = int(p.duration_s * p.imu_hz)
    t   = np.arange(n, dtype=np.float64) * dt

    # ── Track ──────────────────────────────────────────────────────────────────
    xtrk, ytrk = make_track_xy(p.track, 2400, p.loop_m)
    s_tbl, track_len = arc_length_table(xtrk, ytrk)

    # Pre-compute curvature at each sample position (forward pass)
    # We need a rough speed to estimate s_pos.  Use v_base for the first pass.
    v_base_est = 12.0 + 10.0 * p.aggression
    s_positions = np.cumsum(np.full(n, v_base_est * dt))
    s_positions = np.r_[0.0, s_positions[:-1]]

    kappa_raw = np.array([
        track_curvature(xtrk, ytrk, s_tbl, s) for s in s_positions
    ])

    # ── Speed profile ──────────────────────────────────────────────────────────
    v_target = compute_target_speed(kappa_raw, p.aggression)
    spd      = smooth_velocity(v_target, p.aggression, rng)

    # Second-pass: recompute s_positions with realistic speed
    s_pos = np.zeros(n)
    for i in range(1, n):
        s_pos[i] = s_pos[i - 1] + float(spd[i - 1]) * dt

    # Re-sample curvature with corrected positions
    kappa = np.array([track_curvature(xtrk, ytrk, s_tbl, s) for s in s_pos])

    # Track XY and heading
    track_xy_hdg = np.array([sample_track_at(xtrk, ytrk, s_tbl, s) for s in s_pos])
    x_m   = track_xy_hdg[:, 0]
    y_m   = track_xy_hdg[:, 1]
    hdg   = track_xy_hdg[:, 2]

    # ── Events ────────────────────────────────────────────────────────────────
    events   = schedule_events(p.duration_s, p.aggression, rng_py)
    marker   = [""] * n

    # Build per-sample az_event and brake_speed_factor arrays
    az_event    = np.zeros(n)
    brake_hold  = np.zeros(n)   # fractional speed reduction 0..1
    slide_hold  = np.zeros(n)   # additional yaw rate factor 0..1

    for ev in events.values():
        i0 = ev.index
        i1 = min(n, i0 + ev.duration)
        marker[i0] = ev.label

        if ev.label == "JUMP":
            # Airborne phase: reduce az to near-zero
            az_event[i0:i1] += ev.az_delta
            # Landing spike at the END of the airborne phase
            land = min(n - 1, i1)
            spike_dur = max(2, int(0.06 * p.imu_hz))  # ~60 ms spike
            landing_g = (6.0 + 4.0 * p.aggression) * G0
            az_event[land : land + spike_dur] += landing_g

        elif ev.label == "BUMP":
            az_event[i0:i1] += ev.az_delta
            # small forward/lateral jolt
            ax_jolt = ev.ax_delta

        elif ev.label == "BRAKE":
            # Smooth brake ramp: 0→peak→recover over ~2 s
            brake_dur = int(2.0 * p.imu_hz)
            ramp_up   = int(0.3 * p.imu_hz)
            for j in range(min(brake_dur, n - i0)):
                ii = i0 + j
                phase = j / brake_dur
                envelope = math.sin(math.pi * phase)     # 0→1→0
                if j < ramp_up:
                    envelope = j / ramp_up
                brake_hold[ii] = max(brake_hold[ii], envelope * (0.35 + 0.25 * p.aggression))

        elif ev.label == "SLIDE":
            slide_dur = int(1.5 * p.imu_hz)
            for j in range(min(slide_dur, n - i0)):
                ii = i0 + j
                envelope = math.exp(-3.0 * j / slide_dur)
                slide_hold[ii] = max(slide_hold[ii], envelope * (0.5 + 0.4 * p.aggression))

    # Apply brake effect to speed
    spd = spd * (1.0 - brake_hold)
    spd = np.clip(spd, V_MIN_MPS, V_MAX_MPS)

    # ── Accelerations ─────────────────────────────────────────────────────────
    # Longitudinal: dv/dt (smooth speed → safe finite diff)
    dv = np.diff(spd, prepend=spd[0])
    a_lon = np.clip(dv / dt, A_LON_MIN, A_LON_MAX)

    # Lateral: centripetal v²·kappa
    a_lat = np.clip(spd * spd * kappa, -A_LAT_MAX, A_LAT_MAX)

    # Vertical: gravity + events
    az_true = G0 + az_event
    az_true  = np.clip(az_true, -2.5 * G0, AZ_LANDING_MAX)

    # ── Yaw rate ──────────────────────────────────────────────────────────────
    yaw_rate_true = np.clip(
        spd * kappa * (1.0 + 0.6 * slide_hold),
        -YAW_RATE_MAX, YAW_RATE_MAX,
    )

    # ── Attitude integration ─────────────────────────────────────────────────
    roll_arr  = np.zeros(n)
    pitch_arr = np.zeros(n)
    yaw_arr   = np.zeros(n)
    roll  = 0.0
    pitch = 0.0
    yaw   = 0.0

    for i in range(n):
        roll_target  = clamp( 0.04 * float(a_lat[i]),   -ROLL_MAX_RAD,  ROLL_MAX_RAD)
        pitch_target = clamp(-0.03 * float(a_lon[i]),  -PITCH_MAX_RAD, PITCH_MAX_RAD)
        roll  += 0.08 * (roll_target  - roll)  + float(rng.normal(0.0, 0.002))
        pitch += 0.08 * (pitch_target - pitch) + float(rng.normal(0.0, 0.002))
        yaw   += math.degrees(float(yaw_rate_true[i]) * dt)
        while yaw >  180.0: yaw -= 360.0
        while yaw < -180.0: yaw += 360.0
        roll_arr[i]  = math.degrees(roll)
        pitch_arr[i] = math.degrees(pitch)
        yaw_arr[i]   = yaw

    # ── Quaternions ──────────────────────────────────────────────────────────
    qw_arr = np.zeros(n); qx_arr = np.zeros(n)
    qy_arr = np.zeros(n); qz_arr = np.zeros(n)
    for i in range(n):
        qw, qx, qy, qz = euler_to_quat(
            math.radians(roll_arr[i]),
            math.radians(pitch_arr[i]),
            math.radians(yaw_arr[i]),
        )
        qw_arr[i]=qw; qx_arr[i]=qx; qy_arr[i]=qy; qz_arr[i]=qz

    # ── IMU channels with noise + bias wander ─────────────────────────────────
    accel_bias = rng.normal(0.0, ACCEL_BIAS_INIT, 3)
    gyro_bias  = rng.normal(0.0, GYRO_BIAS_INIT,  3)

    ax_out = np.empty(n); ay_out = np.empty(n); az_out = np.empty(n)
    gx_out = np.empty(n); gy_out = np.empty(n); gz_out = np.empty(n)

    for i in range(n):
        accel_bias += rng.normal(0.0, ACCEL_BIAS_WANDER, 3)
        gyro_bias  += rng.normal(0.0, GYRO_BIAS_WANDER,  3)

        ax_out[i] = float(a_lon[i])          + accel_bias[0] + float(rng.normal(0.0, ACCEL_NOISE_STD))
        ay_out[i] = float(a_lat[i])          + accel_bias[1] + float(rng.normal(0.0, ACCEL_NOISE_STD))
        az_out[i] = float(az_true[i])        + accel_bias[2] + float(rng.normal(0.0, ACCEL_NOISE_STD))

        gx_out[i] = 0.0                      + gyro_bias[0]  + float(rng.normal(0.0, GYRO_NOISE_STD))
        gy_out[i] = 0.0                      + gyro_bias[1]  + float(rng.normal(0.0, GYRO_NOISE_STD))
        gz_out[i] = float(yaw_rate_true[i])  + gyro_bias[2]  + float(rng.normal(0.0, GYRO_NOISE_STD))

    # ── GPS (10 Hz hold-and-update with noise) ────────────────────────────────
    gps_stride  = max(1, p.imu_hz // p.gps_hz)
    gps_walk    = np.zeros((n, 2))
    for i in range(1, n):
        gps_walk[i] = gps_walk[i - 1] + rng.normal(0.0, GPS_WALK_STD_M, 2)

    gps_lat  = np.zeros(n); gps_lon  = np.zeros(n)
    gps_hdop = np.zeros(n); gps_sat  = np.zeros(n, dtype=int)
    hold_lat  = p.origin_lat; hold_lon  = p.origin_lon
    hold_hdop = HDOP_NOMINAL; hold_sat  = SAT_NOMINAL

    for i in range(n):
        if i % gps_stride == 0:
            nx = float(rng.normal(0.0, GPS_POS_NOISE_M)) + gps_walk[i, 0]
            ny = float(rng.normal(0.0, GPS_POS_NOISE_M)) + gps_walk[i, 1]
            hold_lat, hold_lon = meters_to_latlon(
                p.origin_lat, p.origin_lon,
                float(x_m[i]) + nx, float(y_m[i]) + ny,
            )
            hold_hdop = float(clamp(
                hold_hdop + float(rng.normal(0.0, HDOP_WANDER_STD)), 0.7, 2.0
            ))
            hold_sat = int(clamp(hold_sat + int(rng.integers(-1, 2)), 8, 20))

        gps_lat[i]  = hold_lat
        gps_lon[i]  = hold_lon
        gps_hdop[i] = hold_hdop
        gps_sat[i]  = hold_sat

    # ── Assemble DataFrame ────────────────────────────────────────────────────
    return pd.DataFrame({
        "t":      t,
        "ax":     ax_out,
        "ay":     ay_out,
        "az":     az_out,
        "gx":     gx_out,
        "gy":     gy_out,
        "gz":     gz_out,
        "lat":    gps_lat,
        "lon":    gps_lon,
        "spd":    spd,
        "hdg":    hdg,
        "roll":   roll_arr,
        "pitch":  pitch_arr,
        "yaw":    yaw_arr,
        "qw":     qw_arr,
        "qx":     qx_arr,
        "qy":     qy_arr,
        "qz":     qz_arr,
        "sat":    gps_sat,
        "hdop":   gps_hdop,
        "marker": marker,
    })


# ── Validation ────────────────────────────────────────────────────────────────

def validate(df: pd.DataFrame, params: GenParams) -> bool:
    """
    Print a physical-plausibility report and return True if all checks pass.
    """
    G = G0
    g_mag = np.sqrt(df.ax**2 + df.ay**2 + df.az**2) / G
    spd_mph = df.spd * 2.236936

    checks = []

    def check(name: str, value: float, lo: float, hi: float, unit: str = "") -> None:
        ok = lo <= value <= hi
        sym = "✓" if ok else "✗"
        checks.append(ok)
        print(f"  {sym}  {name:<30s} {value:8.2f}  [{lo:.1f} – {hi:.1f}]{unit}")

    print("\n── Physical plausibility report ─────────────────────────────────────")
    print(f"   Track: {params.track}   Aggression: {params.aggression:.2f}   "
          f"Seed: {params.seed}   Duration: {params.duration_s:.0f}s")
    print()

    check("Top speed (mph)",            spd_mph.max(),              10, 50)
    check("Mean speed (mph)",           spd_mph.mean(),              8, 38)
    check("Peak |a| (g)",               g_mag.max(),                 0, 15)
    check("Mean |a| (g)",               g_mag.mean(),              0.5,  4)
    check("Peak lateral ay (g)",        abs(df.ay).max() / G,        0,  3)
    check("Peak longitudinal ax (g)",   abs(df.ax).max() / G,        0,  3)
    check("Peak vertical az (g)",       df.az.max() / G,             0, 12)
    check("Min vertical az (g)",        df.az.min() / G,            -3,  2)
    check("Peak yaw rate (deg/s)",      (df.gz.abs() * 57.3).max(), 0, 160)
    check("Peak roll (deg)",            df.roll.abs().max(),          0,  14)
    check("Peak pitch (deg)",           df.pitch.abs().max(),         0,  12)

    # Quaternion unit-norm check (sample 200 points)
    idxs = np.linspace(0, len(df)-1, 200, dtype=int)
    qnorms = np.sqrt(df.qw.values[idxs]**2 + df.qx.values[idxs]**2 +
                     df.qy.values[idxs]**2 + df.qz.values[idxs]**2)
    qnorm_err = float(np.max(np.abs(qnorms - 1.0)))
    q_ok = qnorm_err < 1e-6
    checks.append(q_ok)
    print(f"  {'✓' if q_ok else '✗'}  {'Quaternion unit-norm error':<30s} {qnorm_err:.2e}  [< 1e-6]")

    n_finite = int(np.sum(~np.isfinite(df[["ax","ay","az","lat","lon"]].values)))
    fin_ok = n_finite == 0
    checks.append(fin_ok)
    print(f"  {'✓' if fin_ok else '✗'}  {'Non-finite values':<30s} {n_finite:8d}  [0]")

    markers = {m: int((df.marker == m).sum()) for m in ["JUMP","BUMP","BRAKE","SLIDE"] if (df.marker == m).any()}
    print(f"\n  Events: {markers}")

    passed = sum(checks); total = len(checks)
    print(f"\n  {passed}/{total} checks passed", "✓ OK" if passed == total else "✗ REVIEW NEEDED")
    print("─" * 69)

    return passed == total


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Cross-kart synthetic session generator")
    ap.add_argument("--out",        default="",     help="Output CSV path (auto-named if omitted)")
    ap.add_argument("--duration",   type=float, default=240.0,  help="Session length in seconds")
    ap.add_argument("--imu-hz",     type=int,   default=50)
    ap.add_argument("--gps-hz",     type=int,   default=10)
    ap.add_argument("--track",      default="mixed",
                    choices=["oval", "twisty", "hill", "mixed"])
    ap.add_argument("--aggression", type=float, default=0.70,   help="0.0 (easy) to 1.0 (wild)")
    ap.add_argument("--seed",       type=int,   default=1)
    ap.add_argument("--origin-lat", type=float, default=32.0809)
    ap.add_argument("--origin-lon", type=float, default=-81.0912)
    ap.add_argument("--loop-m",     type=float, default=520.0,  help="Approx track perimeter (m)")
    ap.add_argument("--validate",   action="store_true",        help="Run plausibility checks")
    args = ap.parse_args()

    params = GenParams(
        duration_s  = args.duration,
        imu_hz      = args.imu_hz,
        gps_hz      = args.gps_hz,
        track       = args.track,
        aggression  = clamp(args.aggression, 0.0, 1.0),
        seed        = args.seed,
        origin_lat  = args.origin_lat,
        origin_lon  = args.origin_lon,
        loop_m      = args.loop_m,
    )

    print(f"Generating {params.duration_s:.0f}s {params.track} session "
          f"(aggression={params.aggression:.2f}, seed={params.seed}) …")

    df = generate(params)

    out_path = args.out or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(out_path, index=False)
    print(f"Written: {out_path}  ({len(df)} rows, {len(df.columns)} columns)")

    if args.validate or not args.out:
        validate(df, params)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
