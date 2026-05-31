#!/usr/bin/env python3
"""
Cross-Kart Telemetry Server  (server.py)
=========================================
Flask backend for the canvas-based replay viewer.

Design principles:
  - Session CSV is loaded once into memory and serialised to a compact JSON blob.
  - Every channel is sent as a flat array (column-major).  The browser indexes
    by frame number; no per-request work on the Python side during playback.
  - The server has exactly three routes:
        GET /               → index.html
        GET /api/session    → full session JSON (called once on page load)
        POST /api/upload    → accept a new CSV, replace the current session

Run:
    python server.py [path/to/session.csv]  [--port 5000]

The optional positional argument sets the default session that loads on startup.
If omitted, the viewer shows an upload prompt.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, abort
from scipy.ndimage import gaussian_filter1d

# ── Constants ──────────────────────────────────────────────────────────────────
G0   = 9.80665
MPH  = 2.236936

REQUIRED_COLS = [
    "t", "ax", "ay", "az", "gx", "gy", "gz",
    "lat", "lon", "spd", "hdg",
    "roll", "pitch", "yaw", "qw", "qx", "qy", "qz",
    "sat", "hdop", "marker",
]

HERE     = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "viewer")   # Flask looks for templates here

app = Flask(__name__, template_folder=TEMPLATE, static_folder=os.path.join(TEMPLATE, "static"))

# ── Session state (module-level; one session at a time) ────────────────────────
_session_json: str | None = None   # pre-serialised; served verbatim
_session_name: str        = ""


# ── Session loading ────────────────────────────────────────────────────────────

def _first_lap_end(x_m, y_m):
    """
    Return the frame index where the kart first returns near its start position,
    after having travelled at least 200 m (avoids false positives at the start
    and works regardless of total session length / lap count).
    Used to draw only one clean lap as the static map background.
    """
    dx = np.diff(x_m); dy = np.diff(y_m)
    cum_s = np.r_[0.0, np.cumsum(np.sqrt(dx*dx + dy*dy))]
    min_travel = 200.0  # metres — safely past the departure zone
    threshold  = 25.0   # metres — generous enough to survive GPS noise
    for i in range(len(x_m)):
        if cum_s[i] < min_travel:
            continue
        if math.sqrt((x_m[i] - x_m[0])**2 + (y_m[i] - y_m[0])**2) < threshold:
            return i
    return len(x_m)   # single-lap or out-and-back session: draw everything


def _latlon_to_local(lat, lon, origin_lat, origin_lon):
    cos_lat = math.cos(math.radians(float(origin_lat)))
    x = (lon - origin_lat) * 111_320.0 * cos_lat   # east metres — NOTE: fixed below
    # correct formula:
    x = (lon - origin_lon) * 111_320.0 * cos_lat
    y = (lat - origin_lat) * 111_320.0
    return x, y


def load_csv(path: str) -> tuple[str, str]:
    """
    Parse a session CSV and return (json_string, display_name).
    Raises ValueError with a human-readable message on bad input.
    """
    df = pd.read_csv(path, keep_default_na=False)

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    # Sanitise marker
    df["marker"] = (
        df["marker"].fillna("").astype(str)
        .apply(lambda s: "" if s.strip().lower() == "nan" else s.strip())
    )

    # Drop bad GPS rows
    finite = np.isfinite(df["lat"].to_numpy()) & np.isfinite(df["lon"].to_numpy())
    df = df.loc[finite].reset_index(drop=True)
    if len(df) == 0:
        raise ValueError("No valid GPS rows in session.")

    # Derived channels
    origin_lat = float(df["lat"].iloc[0])
    origin_lon = float(df["lon"].iloc[0])
    x_m, y_m = _latlon_to_local(
        df["lat"].to_numpy(), df["lon"].to_numpy(),
        origin_lat, origin_lon,
    )
    # Smooth GPS noise for map display. sigma=5 samples (0.1 s at 50 Hz) spans
    # one GPS update cycle, blending position steps without blurring corners
    # (tight turns span 80+ samples at racing speeds).
    x_m = gaussian_filter1d(x_m, sigma=5)
    y_m = gaussian_filter1d(y_m, sigma=5)
    lap1_end = _first_lap_end(x_m, y_m)
    spd_mph = df["spd"].to_numpy() * MPH
    g_mag   = np.sqrt(df["ax"]**2 + df["ay"]**2 + df["az"]**2).to_numpy() / G0

    # Infer Hz
    diffs  = np.diff(df["t"].to_numpy()[:500])
    dt_med = float(np.median(diffs[diffs > 0]))
    hz     = round(1.0 / dt_med) if dt_med > 1e-9 else 50

    # Markers as [{idx, t, label}]
    mrows = df[df["marker"] != ""]
    markers = [
        {"idx": int(i), "t": float(df.loc[i, "t"]), "label": str(df.loc[i, "marker"])}
        for i in mrows.index
    ]

    # Build compact column-major payload.
    # Float32 precision is enough for all channels; halves JSON size vs float64.
    def f32(arr):
        return [round(float(v), 5) for v in arr]

    def f16(arr):   # lower precision for less critical channels
        return [round(float(v), 3) for v in arr]

    payload = {
        "meta": {
            "name":       os.path.basename(path),
            "duration":   float(df["t"].iloc[-1]),
            "hz":         hz,
            "n_frames":   len(df),
            "origin_lat": origin_lat,
            "origin_lon": origin_lon,
            "top_mph":    round(float(spd_mph.max()), 1),
            "peak_g":     round(float(g_mag.max()), 3),
            "peak_yaw":   round(float(df["gz"].abs().max() * 57.296), 1),
            "n_events":   len(markers),
            "lap1_end":   lap1_end,
        },
        "markers": markers,
        # Time-series channels (one value per frame)
        "t":     f32(df["t"]),
        "spd":   f16(spd_mph),          # mph
        "g_mag": f16(g_mag),            # g
        "hdg":   f16(df["hdg"]),        # degrees
        "roll":  f16(df["roll"]),       # degrees
        "pitch": f16(df["pitch"]),      # degrees
        "yaw":   f16(df["yaw"]),        # degrees
        "gz":    f16(df["gz"] * 57.296),# yaw rate deg/s
        "ax":    f16(df["ax"] / G0),    # g (body frame)
        "ay":    f16(df["ay"] / G0),
        "az":    f16(df["az"] / G0),
        "qw":    f16(df["qw"]),
        "qx":    f16(df["qx"]),
        "qy":    f16(df["qy"]),
        "qz":    f16(df["qz"]),
        "sat":   [int(v) for v in df["sat"]],
        "hdop":  f16(df["hdop"]),
        "lat":   f32(df["lat"]),
        "lon":   f32(df["lon"]),
        # Map coords in local metres (pre-computed — browser never does trig)
        "x_m":   f16(x_m),
        "y_m":   f16(y_m),
    }

    return json.dumps(payload, separators=(",", ":")), os.path.basename(path)


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", session_loaded=(_session_json is not None))


@app.route("/api/session")
def api_session():
    if _session_json is None:
        abort(404, "No session loaded.")
    # Return pre-serialised JSON directly — avoids double-encoding
    from flask import Response
    return Response(_session_json, mimetype="application/json")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    global _session_json, _session_name
    f = request.files.get("file")
    if f is None or not f.filename.endswith(".csv"):
        abort(400, "Expected a .csv file.")
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name
    try:
        _session_json, _session_name = load_csv(tmp_path)
    except ValueError as e:
        os.unlink(tmp_path)
        abort(400, str(e))
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return jsonify({"ok": True, "name": _session_name})


# ── Entry point ────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Cross-Kart telemetry server")
    p.add_argument("session", nargs="?", help="Path to session CSV to preload")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--host", default="127.0.0.1")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.session:
        path = os.path.abspath(args.session)
        if not os.path.exists(path):
            print(f"ERROR: session file not found: {path}", file=sys.stderr)
            sys.exit(1)
        try:
            _session_json, _session_name = load_csv(path)
            n = json.loads(_session_json)["meta"]["n_frames"]
            print(f"  Loaded: {_session_name}  ({n} frames)")
        except ValueError as e:
            print(f"ERROR loading session: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"  Serving on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
