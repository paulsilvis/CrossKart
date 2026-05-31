"""
Cross-Kart Telemetry Viewer — launcher  (launch.pyw)

Double-click to start the viewer on Windows.
- First run: creates venv and installs dependencies (~1-2 min).
- Subsequent runs: opens browser immediately.
- System tray icon: right-click to reopen or stop.

Requires Python 3.10+ with "Add Python to PATH" checked.
"""

import os
import subprocess
import sys
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox

HERE        = os.path.dirname(os.path.abspath(__file__))
VENV        = os.path.join(HERE, ".venv")
DATA_DIR    = os.path.join(HERE, "data")
SERVER      = os.path.join(HERE, "server.py")
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
PORT        = 5000
URL         = f"http://127.0.0.1:{PORT}"

# Scripts dir differs between Windows and Unix
if sys.platform == "win32":
    PYTHON_VENV = os.path.join(VENV, "Scripts", "python.exe")
    PIP_VENV    = os.path.join(VENV, "Scripts", "pip.exe")
else:
    PYTHON_VENV = os.path.join(VENV, "bin", "python")
    PIP_VENV    = os.path.join(VENV, "bin", "pip")

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

PYTHON = sys.executable.replace("pythonw.exe", "python.exe")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


def die(msg):
    root = tk.Tk(); root.withdraw()
    messagebox.showerror("Cross-Kart launcher", msg)
    sys.exit(1)


def run(cmd, **kw):
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    if sys.platform == "win32":
        kw.setdefault("creationflags", NO_WINDOW)
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() if result.stderr else ""
        die(f"Setup failed:\n{' '.join(str(c) for c in cmd)}\n\n{detail}")


# ── First-run setup ────────────────────────────────────────────────────────────
if not os.path.exists(PYTHON_VENV):
    root = tk.Tk(); root.withdraw()
    messagebox.showinfo(
        "Cross-Kart — first-time setup",
        "Setting up for the first time.\nThis takes about a minute.",
    )
    root.destroy()
    run([PYTHON, "-m", "venv", VENV])
    run([PIP_VENV, "install", "--quiet", "-r", REQUIREMENTS])

# ── Find a default session to preload (newest CSV in data/) ───────────────────
default_session = ""
if os.path.isdir(DATA_DIR):
    csvs = sorted(
        (os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR) if f.endswith(".csv")),
        key=os.path.getmtime, reverse=True,
    )
    if csvs:
        default_session = csvs[0]

# ── Launch Flask server ───────────────────────────────────────────────────────
cmd = [PYTHON_VENV, SERVER, "--port", str(PORT)]
if default_session:
    cmd.append(default_session)

proc = subprocess.Popen(
    cmd,
    cwd=HERE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    creationflags=NO_WINDOW if sys.platform == "win32" else 0,
)

# Wait for server to be ready (poll the port)
import socket
for _ in range(40):
    time.sleep(0.25)
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.2):
            break
    except OSError:
        pass

webbrowser.open(URL)

# ── System tray ───────────────────────────────────────────────────────────────
from PIL import Image, ImageDraw
import pystray

def make_icon():
    img = Image.new("RGB", (64, 64), (8, 11, 18))
    d = ImageDraw.Draw(img)
    sq = 16
    for row in range(4):
        for col in range(4):
            c = (230, 230, 230) if (row + col) % 2 == 0 else (30, 30, 30)
            d.rectangle([col*sq, row*sq, (col+1)*sq-1, (row+1)*sq-1], fill=c)
    return img

def open_viewer(icon, item): webbrowser.open(URL)
def stop_viewer(icon, item): proc.terminate(); icon.stop()

tray = pystray.Icon(
    "CrossKart", make_icon(),
    "Cross-Kart Telemetry  (right-click to stop)",
    menu=pystray.Menu(
        pystray.MenuItem("Open Viewer", open_viewer, default=True),
        pystray.MenuItem("Stop", stop_viewer),
    ),
)
tray.run()
