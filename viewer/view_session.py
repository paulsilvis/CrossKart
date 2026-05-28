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

# Kart wireframe dimensions (metres, body frame: +X fwd, +Y left, +Z up)
KART_PTS = np.array([
    [-0.85, -0.55, -0.25],   # 0 rear-right-bottom
    [ 0.85, -0.55, -0.25],   # 1 front-right-bottom
    [ 0.85,  0.55, -0.25],   # 2 front-left-bottom
    [-0.85,  0.55, -0.25],   # 3 rear-left-bottom
    [-0.85, -0.55,  0.25],   # 4 rear-right-top
    [ 0.85, -0.55,  0.25],   # 5 front-right-top
    [ 0.85,  0.55,  0.25],   # 6 front-left-top
    [-0.85,  0.55,  0.25],   # 7 rear-left-top
], dtype=np.float64)

KART_EDGES = [
    (0,1),(1,2),(2,3),(3,0),   # bottom face
    (4,5),(5,6),(6,7),(7,4),   # top face
    (0,4),(1,5),(2,6),(3,7),   # verticals
]


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


def render_track_map(
    sess: Session,
    idx: int,
    tail_s: float,
    mode: str,            # "full" | "grow" | "local"
    window_idx: Optional[Tuple[int, int]] = None,
) -> plt.Figure:
    """
    Top-down GPS track in local metres.
    - Full/grey path always visible (context)
    - Highlighted section depends on mode
    - Coloured tail shows recent trajectory
    - Gold dot = current position
    - Gold triangles = event markers
    """
    df       = sess.df
    lat_all  = df["lat"].to_numpy()
    lon_all  = df["lon"].to_numpy()
    x_all, y_all = latlon_to_local_m(lat_all, lon_all, sess.origin_lat, sess.origin_lon)
    n        = len(df)
    tail_n   = max(1, int(tail_s * sess.imu_hz))

    fig, ax = plt.subplots(figsize=(5, 5))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    # Full path (dim background)
    ax.plot(x_all, y_all, lw=0.8, color="#333355", zorder=1)

    # Mode-dependent highlight
    if mode == "grow":
        hi_x, hi_y = x_all[:idx+1], y_all[:idx+1]
    elif mode == "local" and window_idx is not None:
        a, b = window_idx
        hi_x, hi_y = x_all[a:b+1], y_all[a:b+1]
    else:   # "full"
        hi_x, hi_y = x_all, y_all

    ax.plot(hi_x, hi_y, lw=1.2, color="#4C9BE8", zorder=2)

    # Tail — round caps so both endpoints look intentional, not clipped.
    # A small dot at the back end marks where the time window begins.
    t0 = max(0, idx - tail_n)
    ax.plot(x_all[t0:idx+1], y_all[t0:idx+1], lw=3.0, color="#E87C4C",
            zorder=3, solid_capstyle="round")
    if t0 < idx:
        ax.scatter([x_all[t0]], [y_all[t0]], s=20, color="#E87C4C",
                   zorder=3, marker="o", linewidths=0)

    # Current position
    ax.scatter([x_all[idx]], [y_all[idx]], s=80, color="#FFD700",
               zorder=5, marker="o", linewidths=0)

    # Event markers (all, always visible)
    mdf = df[df["marker"] != ""]
    if len(mdf):
        mi = mdf.index.to_numpy()
        ax.scatter(x_all[mi], y_all[mi], s=30, color="#FFD700",
                   zorder=4, marker="^", linewidths=0)
        # Label first 20 to avoid clutter
        for j in mi[:20]:
            ax.text(x_all[j], y_all[j], df.loc[j, "marker"],
                    color="#FFD700", fontsize=6, ha="left", va="bottom")

    ax.set_aspect("equal", adjustable="datalim")
    ax.tick_params(colors="white", labelsize=6)
    ax.set_xlabel("East (m)",  color="white", fontsize=7)
    ax.set_ylabel("North (m)", color="white", fontsize=7)
    ax.spines[:].set_color("#444")
    ax.grid(True, lw=0.3, color="#333355")

    title = {"full": "Track (full)", "grow": "Track (growing)", "local": "Track (window)"}
    ax.set_title(title.get(mode, "Track"), color="white", fontsize=8)
    fig.tight_layout(pad=0.5)
    return fig


def render_attitude(
    qw: float, qx: float, qy: float, qz: float,
    ax_ms2: float, ay_ms2: float, az_ms2: float,
) -> plt.Figure:
    """
    Perspective wireframe of the kart rotated by the quaternion.
    Draws:
      - Wireframe box (kart body)
      - Blue arrow: forward (+X) direction
      - Coloured arrow: total G-vector in body frame
    """
    R   = quat_to_rotmat(qw, qx, qy, qz)
    rot = (R @ KART_PTS.T).T          # rotate all vertices
    p2d = perspective_project(rot)    # project to 2D

    g_vec  = np.array([ax_ms2, ay_ms2, az_ms2]) / G0
    g_mag  = float(np.linalg.norm(g_vec))
    g_col  = "#4CE84C" if g_mag < G_YELLOW else ("#FFD700" if g_mag < G_RED else "#E84C4C")

    fig, ax = plt.subplots(figsize=(3.5, 3.5))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    # Wireframe edges
    for a_i, b_i in KART_EDGES:
        ax.plot([p2d[a_i, 0], p2d[b_i, 0]],
                [p2d[a_i, 1], p2d[b_i, 1]],
                lw=1.4, color="#4C9BE8")

    # Forward arrow (+X in body frame, projected)
    fwd_world  = R @ np.array([1.2, 0.0, 0.0])
    fwd_2d     = perspective_project(fwd_world.reshape(1, 3))[0]
    ax.annotate("", xy=fwd_2d, xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color="#4CE8E8", lw=1.5))

    # G-vector arrow (body-frame acceleration, scaled)
    g_world    = R @ (g_vec * 0.65)   # scale for visual clarity
    g_2d       = perspective_project(g_world.reshape(1, 3))[0]
    ax.annotate("", xy=g_2d, xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=g_col, lw=2.5))

    ax.text(0.02, 0.97, f"|a| = {g_mag:.2f} g",
            transform=ax.transAxes, color=g_col,
            fontsize=9, va="top", ha="left",
            bbox=dict(facecolor="#111", edgecolor="none", alpha=0.7))

    ax.set_xlim(-2.0, 2.0)
    ax.set_ylim(-2.0, 2.0)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("Attitude + G-vector", color="white", fontsize=8)
    ax.spines[:].set_color("#333")
    fig.tight_layout(pad=0.3)
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
