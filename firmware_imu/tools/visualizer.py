#!/usr/bin/env python3
"""
CrossKart IMU Visualizer — Phase 1
Reads BNO085 quaternion + accel + gyro from ESP32 serial port.
Renders live 3D orientation + accel bar charts in a matplotlib window.

Usage:
    python visualizer.py              # auto-detect port
    python visualizer.py COM3         # Windows
    python visualizer.py /dev/ttyUSB0 # Linux

Dependencies:
    pip install pyserial matplotlib numpy
"""

import sys
import threading
import queue
import time
import re
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import serial
import serial.tools.list_ports

# ── Port detection ───────────────────────────────────────────────────────────
def find_esp32_port():
    """Return the most likely ESP32 serial port, or None."""
    candidates = []
    for p in serial.tools.list_ports.comports():
        desc = (p.description or "").lower()
        mfr  = (p.manufacturer or "").lower()
        if any(k in desc or k in mfr for k in
               ["cp210", "ch340", "ch341", "ftdi", "silicon", "esp", "uart"]):
            candidates.append(p.device)
    if candidates:
        print(f"Auto-detected port: {candidates[0]}")
        return candidates[0]
    # last resort — first available
    all_ports = [p.device for p in serial.tools.list_ports.comports()]
    if all_ports:
        print(f"No ESP32 signature found; trying {all_ports[0]}")
        return all_ports[0]
    return None

PORT = sys.argv[1] if len(sys.argv) > 1 else find_esp32_port()
BAUD = 115200

# ── Shared state (written by serial thread, read by plot thread) ─────────────
q = queue.Queue(maxsize=50)   # (qi, qj, qk, qr, ax, ay, az, gx, gy, gz, ca, cg, cm)
latest = {
    "qi": 0, "qj": 0, "qk": 0, "qr": 1,
    "ax": 0, "ay": 0, "az": 0,
    "gx": 0, "gy": 0, "gz": 0,
    "cal_a": 0, "cal_g": 0, "cal_m": 0,
    "ts": 0,
    "history_ax": [], "history_ay": [], "history_az": [],
    "history_gx": [], "history_gy": [], "history_gz": [],
    "history_g":  [],
}
HISTORY = 100   # number of samples to keep in strip chart

# ── Serial reader thread ─────────────────────────────────────────────────────
def serial_reader():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        print(f"Opened {PORT} @ {BAUD}")
    except Exception as e:
        print(f"Cannot open {PORT}: {e}")
        return

    while True:
        try:
            line = ser.readline().decode("ascii", errors="ignore").strip()
        except Exception:
            time.sleep(0.05)
            continue

        if not line:
            continue
        if line.startswith("#"):
            print(line)   # echo comments to terminal
            continue

        parts = line.split(",")
        if len(parts) != 15:
            continue
        try:
            ts, qi, qj, qk, qr, ax, ay, az, gx, gy, gz, ca, cg, cm, resets = [
                float(x) for x in parts]
        except ValueError:
            continue

        # Derived g-magnitude (without gravity, from linear accel)
        g_mag = np.sqrt(ax**2 + ay**2 + az**2) / 9.81

        latest["qi"] = qi; latest["qj"] = qj
        latest["qk"] = qk; latest["qr"] = qr
        latest["ax"] = ax; latest["ay"] = ay; latest["az"] = az
        latest["gx"] = gx; latest["gy"] = gy; latest["gz"] = gz
        latest["cal_a"] = int(ca); latest["cal_g"] = int(cg)
        latest["cal_m"] = int(cm); latest["ts"] = ts

        latest["history_ax"].append(ax)
        latest["history_ay"].append(ay)
        latest["history_az"].append(az)
        latest["history_gx"].append(gx)
        latest["history_gy"].append(gy)
        latest["history_gz"].append(gz)
        latest["history_g"].append(g_mag)
        for k in ("history_ax", "history_ay", "history_az",
                  "history_gx", "history_gy", "history_gz", "history_g"):
            if len(latest[k]) > HISTORY:
                latest[k].pop(0)

# ── Quaternion → rotation matrix ─────────────────────────────────────────────
def quat_to_matrix(qi, qj, qk, qr):
    """Return 3×3 rotation matrix from unit quaternion (i,j,k,r)."""
    n = np.sqrt(qi**2 + qj**2 + qk**2 + qr**2)
    if n < 1e-6: return np.eye(3)
    qi, qj, qk, qr = qi/n, qj/n, qk/n, qr/n
    return np.array([
        [1-2*(qj**2+qk**2),  2*(qi*qj-qk*qr),  2*(qi*qk+qj*qr)],
        [2*(qi*qj+qk*qr),  1-2*(qi**2+qk**2),  2*(qj*qk-qi*qr)],
        [2*(qi*qk-qj*qr),  2*(qj*qk+qi*qr),  1-2*(qi**2+qj**2)],
    ])

# ── Kart box geometry (body frame) ───────────────────────────────────────────
def make_kart_faces():
    """Return list of (verts, color) for a simple kart box."""
    # Chassis: 0.3 wide, 0.5 long, 0.1 tall
    W, L, H = 0.3, 0.5, 0.12
    # 8 corners of chassis box
    corners = np.array([
        [-W/2, -L/2,  0  ],
        [ W/2, -L/2,  0  ],
        [ W/2,  L/2,  0  ],
        [-W/2,  L/2,  0  ],
        [-W/2, -L/2,  H  ],
        [ W/2, -L/2,  H  ],
        [ W/2,  L/2,  H  ],
        [-W/2,  L/2,  H  ],
    ])
    faces = [
        ([0,1,2,3], "#c0c0c0"),  # bottom
        ([4,5,6,7], "#e0e020"),  # top (yellow)
        ([0,1,5,4], "#a0a0a0"),  # front
        ([2,3,7,6], "#a0a0a0"),  # rear
        ([0,3,7,4], "#888888"),  # left
        ([1,2,6,5], "#888888"),  # right
    ]
    # Roll bar: thin vertical box at rear
    RW, RH = 0.05, 0.25
    rb = np.array([
        [-RW/2, L/2-0.05,  H ],
        [ RW/2, L/2-0.05,  H ],
        [ RW/2, L/2-0.05,  H+RH],
        [-RW/2, L/2-0.05,  H+RH],
        [-RW/2, L/2+0.05,  H ],
        [ RW/2, L/2+0.05,  H ],
        [ RW/2, L/2+0.05,  H+RH],
        [-RW/2, L/2+0.05,  H+RH],
    ])
    rb_faces = [
        ([0,1,2,3], "#404040"),
        ([4,5,6,7], "#404040"),
        ([0,1,5,4], "#606060"),
        ([2,3,7,6], "#606060"),
        ([0,3,7,4], "#505050"),
        ([1,2,6,5], "#505050"),
    ]
    return corners, faces, rb, rb_faces

CORNERS, FACES, RB_CORNERS, RB_FACES = make_kart_faces()

def draw_kart(ax3d, R):
    """Draw the kart rotated by matrix R."""
    ax3d.cla()
    ax3d.set_xlim(-0.8, 0.8); ax3d.set_ylim(-0.8, 0.8)
    ax3d.set_zlim(-0.8, 0.8)
    ax3d.set_xlabel("X"); ax3d.set_ylabel("Y"); ax3d.set_zlabel("Z")
    ax3d.set_facecolor("#0f0f1a")

    # Draw chassis
    rotated  = (R @ CORNERS.T).T
    rot_rb   = (R @ RB_CORNERS.T).T

    polys = []
    colors = []
    for idx_list, color in FACES:
        polys.append([rotated[i] for i in idx_list])
        colors.append(color)
    for idx_list, color in RB_FACES:
        polys.append([rot_rb[i] for i in idx_list])
        colors.append(color)

    col = Poly3DCollection(polys, alpha=0.85, zsort="average")
    col.set_facecolor(colors)
    col.set_edgecolor("#333333")
    ax3d.add_collection3d(col)

    # Draw body-frame axes
    for vec, clr, lbl in [
        ([1,0,0], "red",   "X"),
        ([0,1,0], "green", "Y"),
        ([0,0,1], "blue",  "Z"),
    ]:
        v = R @ np.array(vec) * 0.6
        ax3d.quiver(0,0,0, v[0],v[1],v[2], color=clr, linewidth=2)
        ax3d.text(v[0]*1.1, v[1]*1.1, v[2]*1.1, lbl, color=clr, fontsize=8)

    ax3d.set_title("Orientation (body frame)", color="white", fontsize=9)

# ── Cal colour ───────────────────────────────────────────────────────────────
CAL_COLORS = ["#cc0000","#cc8800","#aacc00","#00cc44"]
CAL_LABELS = ["UNRELIABLE","LOW","MED","HIGH"]

def cal_bar(ax, values, labels):
    ax.cla()
    ax.set_facecolor("#0f0f1a")
    ax.set_xlim(-0.5, len(values)-0.5)
    ax.set_ylim(0, 3.5)
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels, color="white", fontsize=8)
    ax.set_yticks([0,1,2,3])
    ax.set_yticklabels(CAL_LABELS, color="white", fontsize=7)
    ax.tick_params(axis="y", colors="white")
    ax.spines[:].set_visible(False)
    for i, v in enumerate(values):
        ax.bar(i, v, color=CAL_COLORS[int(v)], width=0.5, zorder=2)
    ax.set_title("Calibration", color="white", fontsize=9)
    ax.set_facecolor("#0f0f1a")

def strip_chart(ax, histories, labels, colors, title, ylabel):
    ax.cla()
    ax.set_facecolor("#0f0f1a")
    ax.spines[:].set_color("#444")
    ax.tick_params(colors="white")
    ax.set_ylabel(ylabel, color="white", fontsize=8)
    ax.set_title(title, color="white", fontsize=9)
    ax.axhline(0, color="#555", linewidth=0.5)
    for hist, label, color in zip(histories, labels, colors):
        if hist:
            ax.plot(hist, label=label, color=color, linewidth=1.2)
    ax.legend(loc="upper left", fontsize=7, framealpha=0.3)
    ax.set_xlim(0, HISTORY)

# ── Main plot loop ───────────────────────────────────────────────────────────
def main():
    if PORT is None:
        print("No serial port found. Plug in the ESP32 first.")
        sys.exit(1)

    t = threading.Thread(target=serial_reader, daemon=True)
    t.start()

    matplotlib.rcParams.update({
        "figure.facecolor": "#0f0f1a",
        "axes.facecolor":   "#0f0f1a",
        "text.color":       "white",
        "axes.labelcolor":  "white",
        "xtick.color":      "white",
        "ytick.color":      "white",
    })

    fig = plt.figure(figsize=(14, 7), facecolor="#0f0f1a")
    fig.suptitle("CrossKart — BNO085 Live", color="white", fontsize=12)

    gs = GridSpec(2, 3, figure=fig,
                  left=0.06, right=0.97, top=0.92, bottom=0.08,
                  hspace=0.45, wspace=0.35)

    ax3d   = fig.add_subplot(gs[:, 0], projection="3d")
    ax_cal = fig.add_subplot(gs[0, 1])
    ax_acc = fig.add_subplot(gs[1, 1])
    ax_gyr = fig.add_subplot(gs[0, 2])
    ax_g   = fig.add_subplot(gs[1, 2])

    ax3d.set_facecolor("#0f0f1a")

    plt.ion()
    plt.show()

    while True:
        ROT_CORRECT = np.array([
            [ 0, -1, 0],
            [ 1,  0, 0],
            [ 0,  0, 1],
        ])
        R = quat_to_matrix(latest["qi"], latest["qj"],
                           latest["qk"], latest["qr"]) @ ROT_CORRECT
        draw_kart(ax3d, R)

        cal_bar(ax_cal,
                [latest["cal_a"], latest["cal_g"], latest["cal_m"]],
                ["Accel", "Gyro", "Mag"])

        strip_chart(ax_acc,
                    [latest["history_ax"], latest["history_ay"], latest["history_az"]],
                    ["X","Y","Z"],
                    ["#ff4444","#44ff44","#4488ff"],
                    "Linear Accel", "m/s²")

        strip_chart(ax_gyr,
                    [latest["history_gx"],
                     latest["history_gy"],
                     latest["history_gz"]],
                    ["X","Y","Z"],
                    ["#ff8844","#88ff44","#44ffcc"],
                    "Gyro", "rad/s")

        strip_chart(ax_g,
                    [latest["history_g"]],
                    ["|G|"],
                    ["#ffdd00"],
                    "G-force magnitude", "G")

        fig.canvas.draw_idle()
        fig.canvas.flush_events()
        time.sleep(0.05)   # ~20 fps UI refresh

if __name__ == "__main__":
    main()
