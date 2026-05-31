#!/usr/bin/env python3
"""
Cross-Kart Telemetry Viewer  (viewer v1)
=========================================
Streamlit-based replay viewer for sessions produced by make_synth_session.py
(and eventually real hardware).

Install:
    pip install streamlit pandas numpy matplotlib

Run:
    streamlit run view_session.py
    streamlit run view_session.py -- --map-mode grow

Schema expected: see docs/session_format.md
    Required columns: t ax ay az gx gy gz lat lon spd hdg
                      roll pitch yaw qw qx qy qz sat hdop marker
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

# ── Constants ─────────────────────────────────────────────────────────────────
G0          = 9.80665
MPH         = 2.236936     # m/s → mph
DEG         = 57.29578     # rad → deg
VERSION     = "v1.0"

# G-force colour thresholds for the attitude panel
G_YELLOW    = 2.0          # g
G_RED       = 4.0          # g

# ── 3-D kart geometry (body frame: +X=fwd, +Y=left, +Z=up) ──────────────────
# Dimensions approximate a real cross-kart: 1.7 m long, 1.2 m wide.
_H   = 0.15    # chassis ride height (m)
_WR  = 0.22    # wheel radius (m)
_WW  = 0.12    # wheel width  (m)
_N_W = 16      # polygon sides per wheel disc

_CHASSIS = np.array([
    [ 0.75, -0.52, _H],
    [ 0.75,  0.52, _H],
    [-0.65,  0.52, _H],
    [-0.65, -0.52, _H],
], dtype=np.float64)

_RB_X, _RB_HW, _RB_H = -0.12, 0.40, 0.70
_ROLLBAR = np.array([
    [_RB_X, -_RB_HW, _H],
    [_RB_X, -_RB_HW, _H + _RB_H],
    [_RB_X,  _RB_HW, _H + _RB_H],
    [_RB_X,  _RB_HW, _H],
], dtype=np.float64)

_SEAT = np.array([
    [ 0.20, -0.28, _H],
    [ 0.20,  0.28, _H],
    [ 0.20,  0.28, _H + 0.40],
    [ 0.20, -0.28, _H + 0.40],
], dtype=np.float64)

_NOSE = np.array([
    [ 0.75, -0.30, _H],
    [ 0.75,  0.30, _H],
    [ 0.95,  0.00, _H + 0.06],
], dtype=np.float64)

_WHEEL_CENTRES = np.array([
    [ 0.62,  0.60, _WR],
    [ 0.62, -0.60, _WR],
    [-0.52,  0.60, _WR],
    [-0.52, -0.60, _WR],
], dtype=np.float64)

_HELM_C = np.array([0.08, 0.0, _H + 0.50], dtype=np.float64)
_HELM_R = 0.18


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Session:
    df:       pd.DataFrame
    duration: float          # seconds
    imu_hz:   float
    origin_lat: float
    origin_lon: float

    @property
    def t(self) -> np.ndarray:
        return self.df["t"].to_numpy()


# ── Session loading ───────────────────────────────────────────────────────────

REQUIRED_COLS = [
    "t", "ax", "ay", "az", "gx", "gy", "gz",
    "lat", "lon", "spd", "hdg",
    "roll", "pitch", "yaw", "qw", "qx", "qy", "qz",
    "sat", "hdop", "marker",
]


@st.cache_data(show_spinner="Loading session …")
def load_session(file_bytes: bytes, filename: str) -> Session:
    """
    Parse and validate a session CSV.  Results are cached — the file is only
    parsed once per upload, even across Streamlit reruns.
    """
    import io
    df = pd.read_csv(io.BytesIO(file_bytes), keep_default_na=False)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        st.error(f"Missing columns: {missing}")
        st.stop()

    # Coerce marker to clean strings — never NaN, never the string "nan"
    df["marker"] = (
        df["marker"]
        .fillna("")
        .astype(str)
        .apply(lambda s: "" if s.strip().lower() == "nan" else s.strip())
    )

    # Drop any rows with non-finite lat/lon (shouldn't exist but belt-and-braces)
    bad = ~(np.isfinite(df["lat"].to_numpy()) & np.isfinite(df["lon"].to_numpy()))
    if bad.any():
        st.warning(f"Dropped {bad.sum()} rows with non-finite lat/lon.")
        df = df.loc[~bad].reset_index(drop=True)

    # Infer IMU sample rate from timestamps
    diffs = np.diff(df["t"].to_numpy()[:500])
    dt_med = float(np.median(diffs[diffs > 0]))
    imu_hz = 1.0 / dt_med if dt_med > 1e-9 else 50.0

    origin_lat = float(df["lat"].iloc[0])
    origin_lon = float(df["lon"].iloc[0])

    return Session(
        df=df,
        duration=float(df["t"].iloc[-1]),
        imu_hz=round(imu_hz),
        origin_lat=origin_lat,
        origin_lon=origin_lon,
    )


# ── Geometry helpers ──────────────────────────────────────────────────────────

def nearest_idx(t_arr: np.ndarray, t_now: float) -> int:
    i = int(np.searchsorted(t_arr, t_now, side="left"))
    i = max(0, min(len(t_arr) - 1, i))
    if i > 0 and abs(t_arr[i - 1] - t_now) < abs(t_arr[i] - t_now):
        return i - 1
    return i


def quat_to_rotmat(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    """Unit quaternion → 3×3 rotation matrix."""
    return np.array([
        [1-2*(qy*qy+qz*qz),   2*(qx*qy-qw*qz),   2*(qx*qz+qw*qy)],
        [  2*(qx*qy+qw*qz), 1-2*(qx*qx+qz*qz),   2*(qy*qz-qw*qx)],
        [  2*(qx*qz-qw*qy),   2*(qy*qz+qw*qx), 1-2*(qx*qx+qy*qy)],
    ], dtype=np.float64)


def perspective_project(pts3d: np.ndarray, d: float = 2.8) -> np.ndarray:
    """
    Simple perspective projection onto XY plane.
    d = camera distance behind origin along -Z.
    Returns (N, 2) array of screen coords.
    """
    z = pts3d[:, 2]
    k = d / (d - z)
    return np.column_stack([pts3d[:, 0] * k, pts3d[:, 1] * k])


def latlon_to_local_m(
    lat: np.ndarray, lon: np.ndarray,
    origin_lat: float, origin_lon: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert lat/lon arrays to local East/North metres from origin."""
    cos_lat = math.cos(math.radians(origin_lat))
    x_m = (lon - origin_lon) * 111_320.0 * cos_lat
    y_m = (lat - origin_lat) * 111_320.0
    return x_m, y_m


def gmag(df: pd.DataFrame) -> np.ndarray:
    return np.sqrt(df["ax"]**2 + df["ay"]**2 + df["az"]**2).to_numpy() / G0


# ── Render functions ──────────────────────────────────────────────────────────

def render_timeseries(
    sess: Session,
    idx: int,
    window_s: float,
) -> plt.Figure:
    """
    Rolling window plot: speed (mph), |a| (g), yaw rate (deg/s).
    A vertical cursor marks the current playhead position.
    """
    df   = sess.df
    t    = sess.t
    half = int((window_s / 2.0) * sess.imu_hz)
    i0   = max(0, idx - half)
    i1   = min(len(df) - 1, idx + half)

    tseg     = t[i0:i1+1]
    spd_mph  = df["spd"].to_numpy()[i0:i1+1] * MPH
    g_arr    = gmag(df)[i0:i1+1]
    yaw_dps  = np.abs(df["gz"].to_numpy()[i0:i1+1]) * DEG

    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.plot(tseg, spd_mph,  lw=1.4, label="Speed (mph)",        color="#4C9BE8")
    ax.plot(tseg, g_arr,    lw=1.4, label="|a| (g)",            color="#E87C4C")
    ax.plot(tseg, yaw_dps,  lw=1.0, label="Yaw rate (deg/s)",   color="#7CE87C", alpha=0.8)
    ax.axvline(t[idx], color="white", lw=1.8, ls="--", alpha=0.9)

    # Marker flags in the window
    mdf = df.iloc[i0:i1+1]
    for _, row in mdf[mdf["marker"] != ""].iterrows():
        ax.axvline(float(row["t"]), color="#FFD700", lw=1.0, alpha=0.7)
        ax.text(float(row["t"]), ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 10,
                row["marker"], color="#FFD700", fontsize=7, rotation=90,
                va="top", ha="right")

    ax.set_xlabel("Time (s)", fontsize=8)
    ax.set_facecolor("#1a1a2e")
    fig.patch.set_facecolor("#1a1a2e")
    ax.tick_params(colors="white", labelsize=7)
    ax.xaxis.label.set_color("white")
    ax.spines[:].set_color("#444")
    ax.grid(True, lw=0.3, color="#444")
    ax.legend(loc="upper right", fontsize=7, facecolor="#222", labelcolor="white",
              framealpha=0.8)
    fig.tight_layout(pad=0.5)
    return fig


def _kart_scale(x_all: np.ndarray, y_all: np.ndarray) -> float:
    """Return a kart marker size scaled to ~3.5% of the shorter track dimension."""
    xr = float(x_all.max() - x_all.min())
    yr = float(y_all.max() - y_all.min())
    return max(2.0, min(xr, yr) * 0.035)


def _speed_color(speed_mph: float, max_mph: float = 40.0) -> tuple:
    """Map speed to a RdYlGn colour (slow=red, fast=green)."""
    norm = float(np.clip(speed_mph / max_mph, 0.0, 1.0))
    return plt.cm.RdYlGn(0.15 + norm * 0.75)


def draw_kart_marker(
    ax: plt.Axes,
    x: float, y: float,
    heading_deg: float,
    speed_mph: float,
    scale: float,
) -> None:
    """
    Draw a top-down kart silhouette at map position (x, y).

    heading_deg : compass bearing (0 = North, 90 = East)
    scale       : overall size in map metres; kart body is ~1.1 × scale long
    """
    from matplotlib.patches import Circle

    # Convert compass heading → screen angle (matplotlib: 0=East, CCW positive)
    angle_rad = np.radians(90.0 - heading_deg)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
    s = scale

    def rot(pts: np.ndarray) -> np.ndarray:
        """Rotate local kart coords (+x fwd, +y left) → world map coords."""
        rx = pts[:, 0] * cos_a - pts[:, 1] * sin_a
        ry = pts[:, 0] * sin_a + pts[:, 1] * cos_a
        return np.column_stack([rx + x, ry + y])

    body_color = _speed_color(speed_mph)

    # ── Glow halo (two translucent circles under everything) ──────────────────
    ax.add_patch(Circle((x, y), s * 0.80, color=body_color, alpha=0.10, zorder=8))
    ax.add_patch(Circle((x, y), s * 0.55, color=body_color, alpha=0.12, zorder=8))

    # ── Body silhouette (tapered, wider at rear) ──────────────────────────────
    body_local = np.array([
        [ 0.55,  0.00],   # nose tip
        [ 0.45,  0.18],   # front-left shoulder
        [ 0.20,  0.28],   # mid-left
        [-0.30,  0.30],   # rear-left
        [-0.55,  0.22],   # rear-left corner
        [-0.55, -0.22],   # rear-right corner
        [-0.30, -0.30],   # rear-right
        [ 0.20, -0.28],   # mid-right
        [ 0.45, -0.18],   # front-right shoulder
        [ 0.55,  0.00],   # back to nose
    ]) * s
    ax.add_patch(plt.Polygon(
        rot(body_local), closed=True,
        facecolor=body_color, edgecolor="white",
        linewidth=1.4, zorder=10, alpha=0.96,
    ))

    # ── Roll bar (dark band across the rear third of the body) ────────────────
    rollbar_local = np.array([
        [-0.12,  0.24],
        [-0.12, -0.24],
        [-0.30, -0.24],
        [-0.30,  0.24],
    ]) * s
    ax.add_patch(plt.Polygon(
        rot(rollbar_local), closed=True,
        facecolor="#2a2a2a", edgecolor="#888888",
        linewidth=0.8, zorder=11, alpha=0.85,
    ))

    # ── Four wheels ───────────────────────────────────────────────────────────
    # Positions in kart-local fraction-of-s coords
    wheel_positions = [
        ( 0.38,  0.35),   # front-left
        ( 0.38, -0.35),   # front-right
        (-0.38,  0.35),   # rear-left
        (-0.38, -0.35),   # rear-right
    ]
    ww = 0.22 * s   # wheel length (along kart axis)
    wh = 0.12 * s   # wheel width  (across kart axis)

    for wx, wy in wheel_positions:
        wpts = np.array([
            [wx * s - ww / 2, wy * s - wh / 2],
            [wx * s + ww / 2, wy * s - wh / 2],
            [wx * s + ww / 2, wy * s + wh / 2],
            [wx * s - ww / 2, wy * s + wh / 2],
        ])
        ax.add_patch(plt.Polygon(
            rot(wpts), closed=True,
            facecolor="#111111", edgecolor="#cccccc",
            linewidth=1.0, zorder=12,
        ))

    # ── Gold nose dot ─────────────────────────────────────────────────────────
    nose_world = rot(np.array([[0.60 * s, 0.0]]))[0]
    ax.scatter(
        [nose_world[0]], [nose_world[1]],
        s=22, color="#FFD700", zorder=13, linewidths=0,
    )


def draw_speed_trail(
    ax: plt.Axes,
    x_seg: np.ndarray,
    y_seg: np.ndarray,
    spd_seg: np.ndarray,   # m/s
    max_mph: float = 40.0,
) -> None:
    """
    Draw the recent trajectory as a speed-coloured LineCollection.
    Colour map: slow = red, fast = green  (RdYlGn).
    """
    import matplotlib.collections as mc

    if len(x_seg) < 2:
        return

    points   = np.array([x_seg, y_seg]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    spd_norm = np.clip(spd_seg[:-1] * MPH / max_mph, 0.0, 1.0)

    lc = mc.LineCollection(
        segments,
        cmap="RdYlGn",
        norm=plt.Normalize(0.0, 1.0),
        linewidth=4.5,
        capstyle="round",
        zorder=5,
    )
    lc.set_array(spd_norm)
    ax.add_collection(lc)


def render_track_map(
    sess: Session,
    idx: int,
    tail_s: float,
    mode: str,            # "full" | "grow" | "local"
    window_idx: Optional[Tuple[int, int]] = None,
) -> plt.Figure:
    """
    Top-down GPS track in local metres.

    Improvements over v1:
    - Speed-coloured tail (RdYlGn) instead of flat orange
    - Top-down kart silhouette with wheels, roll bar, and glow halo
    - Kart auto-scales to ~3.5% of the shorter track dimension
    - Darker, higher-contrast background
    """
    df      = sess.df
    x_all, y_all = latlon_to_local_m(
        df["lat"].to_numpy(), df["lon"].to_numpy(),
        sess.origin_lat, sess.origin_lon,
    )
    tail_n  = max(1, int(tail_s * sess.imu_hz))
    scale   = _kart_scale(x_all, y_all)

    fig, ax = plt.subplots(figsize=(5, 5))
    fig.patch.set_facecolor("#0f0f1a")
    ax.set_facecolor("#0f0f1a")

    # ── Full path (dim background) ────────────────────────────────────────────
    ax.plot(x_all, y_all, lw=0.9, color="#1a1a3e", zorder=1)

    # ── Mode-dependent highlight ──────────────────────────────────────────────
    if mode == "grow":
        hi_x, hi_y = x_all[:idx + 1], y_all[:idx + 1]
    elif mode == "local" and window_idx is not None:
        a, b = window_idx
        hi_x, hi_y = x_all[a:b + 1], y_all[a:b + 1]
    else:   # "full"
        hi_x, hi_y = x_all, y_all

    ax.plot(hi_x, hi_y, lw=1.2, color="#2a3a6e", zorder=2)

    # ── Speed-coloured tail ───────────────────────────────────────────────────
    t0 = max(0, idx - tail_n)
    draw_speed_trail(
        ax,
        x_all[t0:idx + 1],
        y_all[t0:idx + 1],
        df["spd"].to_numpy()[t0:idx + 1],
    )

    # ── Kart silhouette ───────────────────────────────────────────────────────
    row = df.iloc[idx]
    draw_kart_marker(
        ax,
        float(x_all[idx]), float(y_all[idx]),
        float(row["hdg"]),
        float(row["spd"]) * MPH,
        scale,
    )

    # ── Event markers ─────────────────────────────────────────────────────────
    mdf = df[df["marker"] != ""]
    if len(mdf):
        mi = mdf.index.to_numpy()
        ax.scatter(x_all[mi], y_all[mi], s=28, color="#FFD700",
                   zorder=4, marker="^", linewidths=0)
        for j in mi[:20]:
            ax.text(x_all[j], y_all[j], df.loc[j, "marker"],
                    color="#FFD700", fontsize=6, ha="left", va="bottom")

    ax.set_aspect("equal", adjustable="datalim")
    ax.tick_params(colors="#555555", labelsize=6)
    ax.set_xlabel("East (m)",  color="#555555", fontsize=7)
    ax.set_ylabel("North (m)", color="#555555", fontsize=7)
    ax.spines[:].set_color("#222222")
    ax.grid(True, lw=0.3, color="#0d0d28")

    title = {"full": "Track (full)", "grow": "Track (growing)", "local": "Track (window)"}
    ax.set_title(title.get(mode, "Track"), color="#888888", fontsize=8)
    fig.tight_layout(pad=0.5)
    return fig


def render_attitude(
    qw: float, qx: float, qy: float, qz: float,
    ax_ms2: float, ay_ms2: float, az_ms2: float,
    speed_mph: float = 0.0,
) -> plt.Figure:
    """
    Chase-cam 3-D view of the kart rotated by the quaternion.

    Camera sits ~5 ft behind and ~5 ft above the kart, looking forward —
    the same POV used in racing games.  Roll and pitch are immediately
    readable from the horizon tilt and nose angle.

    Draws: chassis panel, roll bar, seat, nose wedge, four wheels with
    spokes, driver helmet with visor, G-vector arrow, forward arrow,
    ground-plane grid.
    """
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    R      = quat_to_rotmat(qw, qx, qy, qz)
    g_vec  = np.array([ax_ms2, ay_ms2, az_ms2])
    g_mag  = float(np.linalg.norm(g_vec)) / G0
    g_col  = "#4CE84C" if g_mag < G_YELLOW else ("#FFD700" if g_mag < G_RED else "#E84C4C")
    sp_norm = float(np.clip(speed_mph / 40.0, 0.0, 1.0))
    body_col = plt.cm.RdYlGn(0.15 + sp_norm * 0.75)

    def Rp(pts: np.ndarray) -> np.ndarray:
        """Rotate body-frame points into world frame."""
        return (R @ pts.T).T

    fig = plt.figure(figsize=(3.8, 3.8), facecolor="#0f0f1a")
    ax3 = fig.add_subplot(111, projection="3d", facecolor="#0f0f1a")

    # ── Ground grid ───────────────────────────────────────────────────────────
    gc = "#111133"
    for xi in np.linspace(-2.2, 2.2, 10):
        ax3.plot([xi, xi], [-2.2, 2.2], [0, 0], color=gc, lw=0.5, zorder=0)
    for yi in np.linspace(-2.2, 2.2, 10):
        ax3.plot([-2.2, 2.2], [yi, yi], [0, 0], color=gc, lw=0.5, zorder=0)

    # ── Chassis floor panel ───────────────────────────────────────────────────
    ch = Rp(_CHASSIS)
    ax3.add_collection3d(Poly3DCollection(
        [ch], alpha=0.30, facecolor=body_col, edgecolor="#888888", lw=1.2))
    ch_c = np.vstack([ch, ch[0]])
    ax3.plot(ch_c[:, 0], ch_c[:, 1], ch_c[:, 2], color="#aaaaaa", lw=1.8)

    # ── Nose wedge ────────────────────────────────────────────────────────────
    ax3.add_collection3d(Poly3DCollection(
        [Rp(_NOSE)], alpha=0.75, facecolor=body_col, edgecolor="white", lw=1.0))

    # ── Seat back ─────────────────────────────────────────────────────────────
    ax3.add_collection3d(Poly3DCollection(
        [Rp(_SEAT)], alpha=0.65, facecolor="#2a2a2a", edgecolor="#666666", lw=0.8))

    # ── Roll bar ──────────────────────────────────────────────────────────────
    rb = Rp(_ROLLBAR)
    rb_c = np.vstack([rb, rb[0]])
    ax3.plot(rb_c[:, 0], rb_c[:, 1], rb_c[:, 2], color="#cccccc", lw=3.5, zorder=4)

    # ── Wheels ────────────────────────────────────────────────────────────────
    angles = np.linspace(0, 2 * math.pi, _N_W, endpoint=False)
    for wx, wy, wz in _WHEEL_CENTRES:
        # Inner and outer disc faces
        face_in = Rp(np.column_stack([
            wx + _WR * np.cos(angles),
            np.full(_N_W, wy - np.sign(wy) * _WW / 2),
            wz + _WR * np.sin(angles),
        ]))
        face_out = Rp(np.column_stack([
            wx + _WR * np.cos(angles),
            np.full(_N_W, wy + np.sign(wy) * _WW / 2),
            wz + _WR * np.sin(angles),
        ]))
        for face in (face_in, face_out):
            ax3.add_collection3d(Poly3DCollection(
                [face], alpha=0.92, facecolor="#111111", edgecolor="#bbbbbb", lw=0.8))

        # Three spokes
        for sa in [0.0, math.pi * 2 / 3, math.pi * 4 / 3]:
            sp = Rp(np.array([
                [wx, wy, wz],
                [wx + _WR * 0.82 * math.cos(sa), wy, wz + _WR * 0.82 * math.sin(sa)],
            ]))
            ax3.plot(sp[:, 0], sp[:, 1], sp[:, 2], color="#555555", lw=1.2)

        # Axle stub
        axle = Rp(np.array([
            [wx, wy - _WW * 0.6, wz],
            [wx, wy + _WW * 0.6, wz],
        ]))
        ax3.plot(axle[:, 0], axle[:, 1], axle[:, 2], color="#888888", lw=2.5)

    # ── Helmet ────────────────────────────────────────────────────────────────
    hc_w = Rp(_HELM_C.reshape(1, 3))[0]
    u_h, v_h = np.mgrid[0:math.pi:8j, 0:2*math.pi:12j]
    hx = hc_w[0] + _HELM_R * np.sin(u_h) * np.cos(v_h)
    hy = hc_w[1] + _HELM_R * np.sin(u_h) * np.sin(v_h)
    hz = hc_w[2] + _HELM_R * np.cos(u_h)
    ax3.plot_surface(hx, hy, hz, color="#cc3300", alpha=0.92, linewidth=0, zorder=5)

    # Visor
    visor = Rp(np.array([
        [_HELM_C[0] + _HELM_R * 0.60,  _HELM_C[1] - _HELM_R * 0.50, _HELM_C[2] + _HELM_R * 0.10],
        [_HELM_C[0] + _HELM_R * 0.60,  _HELM_C[1] + _HELM_R * 0.50, _HELM_C[2] + _HELM_R * 0.10],
        [_HELM_C[0] + _HELM_R * 0.55,  _HELM_C[1] + _HELM_R * 0.50, _HELM_C[2] - _HELM_R * 0.30],
        [_HELM_C[0] + _HELM_R * 0.55,  _HELM_C[1] - _HELM_R * 0.50, _HELM_C[2] - _HELM_R * 0.30],
    ]))
    ax3.add_collection3d(Poly3DCollection(
        [visor], alpha=0.70, facecolor="#88ccff", edgecolor="#445566", lw=0.5))

    # ── Arrows ────────────────────────────────────────────────────────────────
    # G-vector (in body frame → world)
    g_world = R @ (g_vec / G0 * 0.55)
    ax3.quiver(0, 0, _H + 0.30,
               g_world[0], g_world[1], g_world[2],
               color=g_col, linewidth=2.5, arrow_length_ratio=0.28, zorder=6)

    # Forward direction
    fwd = R @ np.array([0.9, 0.0, 0.0])
    ax3.quiver(0, 0, _H + 0.10,
               fwd[0], fwd[1], fwd[2],
               color="#4CE8E8", linewidth=1.5, arrow_length_ratio=0.30)

    # ── HUD labels ────────────────────────────────────────────────────────────
    roll_deg  = math.degrees(math.atan2(
        2*(qw*qx + qy*qz), 1 - 2*(qx*qx + qy*qy)))
    pitch_deg = math.degrees(math.asin(
        max(-1.0, min(1.0, 2*(qw*qy - qz*qx)))))

    ax3.text2D(0.03, 0.97, f"|a| = {g_mag:.2f} g",
               transform=ax3.transAxes, color=g_col, fontsize=9, va="top",
               bbox=dict(facecolor="#111", edgecolor="none", alpha=0.75))
    ax3.text2D(0.03, 0.87, f"{speed_mph:.1f} mph",
               transform=ax3.transAxes, color="white", fontsize=9, va="top",
               bbox=dict(facecolor="#111", edgecolor="none", alpha=0.75))
    ax3.text2D(0.03, 0.77, f"R {roll_deg:+.1f}°  P {pitch_deg:+.1f}°",
               transform=ax3.transAxes, color="#aaaaaa", fontsize=8, va="top",
               bbox=dict(facecolor="#111", edgecolor="none", alpha=0.75))

    # ── Camera — chase-cam POV: behind and slightly above ─────────────────────
    # elev=18° above horizon, azim=-155° puts the kart nose pointing away
    ax3.view_init(elev=18, azim=-155)
    ax3.set_xlim(-0.67, 0.67)
    ax3.set_ylim(-0.67, 0.67)
    ax3.set_zlim(-0.02, 0.60)
    ax3.set_box_aspect([4, 4, 2])
    ax3.set_xticks([]); ax3.set_yticks([]); ax3.set_zticks([])
    ax3.set_title("Chase-cam view", color="#888888", fontsize=8, pad=2)

    # Hide pane backgrounds
    for pane in (ax3.xaxis.pane, ax3.yaxis.pane, ax3.zaxis.pane):
        pane.fill = False
        pane.set_edgecolor("#111111")
    ax3.grid(False)

    fig.tight_layout(pad=0.2)
    return fig


# ── Playback state ─────────────────────────────────────────────────────────────

def init_state() -> None:
    for key, default in [
        ("playhead",       0.0),
        ("playing",        False),
        ("last_tick",      None),
        ("loaded_file",    None),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default


def advance_playhead(duration: float, speed: float) -> None:
    """Move playhead forward by real elapsed time × speed multiplier."""
    now = time.monotonic()
    if st.session_state.last_tick is None:
        st.session_state.last_tick = now
        return
    dt_real = now - float(st.session_state.last_tick)
    st.session_state.last_tick = now
    st.session_state.playhead = float(
        min(duration, st.session_state.playhead + dt_real * speed)
    )
    if st.session_state.playhead >= duration:
        st.session_state.playing = False


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--map-mode", default="full",
                   choices=["full", "grow", "local"])
    return p.parse_known_args()[0]


CLI = parse_args()


def main() -> None:
    st.set_page_config(
        page_title="Cross-Kart Telemetry",
        page_icon="🏁",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Dark CSS tweak
    st.markdown("""
        <style>
        .stApp { background-color: #0f0f1a; color: white; }
        .metric-value { font-size: 1.4rem !important; }
        </style>
    """, unsafe_allow_html=True)

    st.title("🏁 Cross-Kart Telemetry Viewer  " + VERSION)

    init_state()

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Session")
        upload = st.file_uploader("Load CSV", type=["csv"])

        if upload is None:
            st.info("Upload a session CSV to begin.")
            st.stop()

        # Reload only when a new file is selected
        file_key = (upload.name, upload.size)
        if st.session_state.loaded_file != file_key:
            st.session_state.playhead    = 0.0
            st.session_state.playing     = False
            st.session_state.last_tick   = None
            st.session_state.loaded_file = file_key

        sess = load_session(upload.read(), upload.name)
        df   = sess.df
        t    = sess.t

        st.caption(f"{upload.name}  ·  {sess.duration:.0f}s  ·  {sess.imu_hz:.0f} Hz")

        st.divider()
        st.header("Playback")

        col_play, col_stop = st.columns(2)
        with col_play:
            if st.button("▶ Play" if not st.session_state.playing else "⏸ Pause"):
                st.session_state.playing     = not st.session_state.playing
                st.session_state.last_tick   = None
        with col_stop:
            if st.button("⏹ Reset"):
                st.session_state.playhead    = 0.0
                st.session_state.playing     = False
                st.session_state.last_tick   = None

        speed     = st.select_slider("Speed", [0.25, 0.5, 1.0, 2.0, 4.0], value=1.0)
        window_s  = st.slider("Plot window (s)", 10.0, 90.0, 40.0, 5.0)
        tail_s    = st.slider("Map tail (s)",     1.0, 15.0,  4.0, 0.5)

        st.divider()
        st.header("Map")
        map_mode = st.selectbox("Mode", ["full", "grow", "local"],
                                index=["full", "grow", "local"].index(CLI.map_mode))

        # Jump-to-marker
        markers_df = df[df["marker"] != ""]
        if len(markers_df):
            st.divider()
            st.header("Markers")
            opts = ["(none)"] + [
                f"{row['marker']}  @  {row['t']:.1f}s"
                for _, row in markers_df.iterrows()
            ]
            pick = st.selectbox("Jump to", opts)
            if pick != "(none)":
                j = opts.index(pick) - 1
                tgt = float(markers_df.iloc[j]["t"])
                if st.button("Go"):
                    st.session_state.playhead = tgt
                    st.session_state.playing  = False

    # ── Advance playhead ───────────────────────────────────────────────────────
    if st.session_state.playing:
        advance_playhead(sess.duration, float(speed))

    # ── Timeline scrubber ─────────────────────────────────────────────────────
    # Keep the slider thumb in sync with the advancing playhead during playback.
    # Without this, Streamlit ignores the `value` arg on reruns and the thumb
    # stays frozen; pausing then snaps the playhead back to the stale position.
    if st.session_state.playing:
        st.session_state["timeline_slider"] = st.session_state.playhead
    t_now = st.slider(
        "Timeline",
        0.0, sess.duration,
        float(st.session_state.playhead),
        step=0.02,
        format="%.1f s",
        disabled=st.session_state.playing,
        key="timeline_slider",
    )
    if not st.session_state.playing:
        st.session_state.playhead = float(t_now)

    idx = nearest_idx(t, float(st.session_state.playhead))

    # ── Session-wide stats ────────────────────────────────────────────────────
    g_all     = gmag(df)
    top_mph   = float(df["spd"].max() * MPH)
    peak_g    = float(g_all.max())
    peak_yaw  = float(df["gz"].abs().max() * DEG)
    n_events  = int((df["marker"] != "").sum())

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Top speed",  f"{top_mph:.1f} mph")
    sc2.metric("Peak |a|",   f"{peak_g:.2f} g")
    sc3.metric("Peak yaw",   f"{peak_yaw:.0f} °/s")
    sc4.metric("Events",     str(n_events))

    st.divider()

    # ── Current-frame values ──────────────────────────────────────────────────
    row      = df.iloc[idx]
    spd_now  = float(row["spd"]) * MPH
    g_now    = math.sqrt(float(row["ax"])**2 + float(row["ay"])**2 + float(row["az"])**2) / G0
    yaw_now  = float(row["gz"]) * DEG
    hdg_now  = float(row["hdg"])
    roll_now = float(row["roll"])
    pit_now  = float(row["pitch"])
    m_now    = str(row["marker"])

    # Active marker banner
    if m_now:
        st.warning(f"**{m_now}**  ·  t = {t[idx]:.2f} s", icon="🚩")

    cv1, cv2, cv3, cv4, cv5, cv6 = st.columns(6)
    cv1.metric("t",       f"{t[idx]:.2f} s")
    cv2.metric("Speed",   f"{spd_now:.1f} mph")
    cv3.metric("|a|",     f"{g_now:.2f} g")
    cv4.metric("Yaw",     f"{yaw_now:.1f} °/s")
    cv5.metric("Roll",    f"{roll_now:.1f}°")
    cv6.metric("Pitch",   f"{pit_now:.1f}°")

    st.divider()

    # ── Main panels ───────────────────────────────────────────────────────────
    left, right = st.columns([2, 1])

    # Compute time-window index bounds (shared between timeseries and local map)
    half    = int((float(window_s) / 2.0) * sess.imu_hz)
    win_i0  = max(0, idx - half)
    win_i1  = min(len(df) - 1, idx + half)

    with left:
        ts_fig = render_timeseries(sess, idx, float(window_s))
        st.pyplot(ts_fig, width='stretch')
        plt.close(ts_fig)

        map_fig = render_track_map(
            sess, idx,
            tail_s=float(tail_s),
            mode=map_mode,
            window_idx=(win_i0, win_i1) if map_mode == "local" else None,
        )
        st.pyplot(map_fig, width='stretch')
        plt.close(map_fig)

    with right:
        att_fig = render_attitude(
            float(row["qw"]), float(row["qx"]),
            float(row["qy"]), float(row["qz"]),
            float(row["ax"]), float(row["ay"]), float(row["az"]),
            speed_mph=spd_now,
        )
        st.pyplot(att_fig, width='stretch')
        plt.close(att_fig)

        st.subheader("Attitude")
        st.write(f"Roll  {roll_now:+.1f}°  ·  Pitch  {pit_now:+.1f}°")
        st.write(f"Yaw   {float(row['yaw']):+.1f}°  ·  Hdg  {hdg_now:.0f}°")

        st.subheader("GPS")
        st.write(f"Sats: {int(row['sat'])}  ·  HDOP: {float(row['hdop']):.2f}")
        st.write(f"{float(row['lat']):.6f}°N  {float(row['lon']):.6f}°E")

        st.subheader("IMU (m/s²)")
        st.write(
            f"ax {float(row['ax']):+.2f}  "
            f"ay {float(row['ay']):+.2f}  "
            f"az {float(row['az']):+.2f}"
        )
        st.write(
            f"gx {float(row['gx']):+.3f}  "
            f"gy {float(row['gy']):+.3f}  "
            f"gz {float(row['gz']):+.3f}  rad/s"
        )

    # ── Animation loop ────────────────────────────────────────────────────────
    # Streamlit has no native animation timer; we sleep briefly and rerun.
    # This gives ~20 fps at 1× playback speed — adequate for telemetry replay.
    if st.session_state.playing and st.session_state.playhead < sess.duration:
        time.sleep(0.05)
        st.rerun()


if __name__ == "__main__":
    main()
