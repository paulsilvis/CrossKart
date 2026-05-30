"""
Cross-Kart Telemetry Viewer — Windows launcher

Double-click this file to start the viewer.
- First run: creates a virtual environment and installs dependencies (~1 min).
- After that: opens the viewer in your browser immediately.

Requires Python 3.10+ installed from https://www.python.org/downloads/
(check "Add Python to PATH" during install).
"""

import os
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HERE, ".venv")
STREAMLIT = os.path.join(VENV, "Scripts", "streamlit.exe")
PIP = os.path.join(VENV, "Scripts", "pip.exe")
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
VIEWER = os.path.join(HERE, "viewer", "view_session.py")

NO_WINDOW = 0x08000000  # Windows: suppress console window for subprocesses

# sys.executable under pythonw.exe is pythonw.exe, which can't run venv/pip.
# Swap in python.exe from the same directory for setup work.
PYTHON = sys.executable.replace("pythonw.exe", "python.exe")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable


def die(msg):
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Cross-Kart launcher error", msg)
    sys.exit(1)


def run(cmd, **kwargs):
    kwargs.setdefault("creationflags", NO_WINDOW)
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip() if result.stderr else ""
        die(
            f"Setup step failed (exit {result.returncode}):\n\n"
            + " ".join(str(c) for c in cmd)
            + (f"\n\n{detail}" if detail else "")
            + "\n\nCheck that Python is installed and try again."
        )


def first_run_notice():
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        "Cross-Kart — first-time setup",
        "Setting up for the first time.\n\n"
        "This will take about a minute. The viewer will open automatically when ready.",
    )
    root.destroy()


# ── First-run setup ───────────────────────────────────────────────────────────

if not os.path.exists(STREAMLIT):
    first_run_notice()
    run([PYTHON, "-m", "venv", VENV])
    run([PIP, "install", "--quiet", "-r", REQUIREMENTS])

# ── Launch Streamlit ──────────────────────────────────────────────────────────

subprocess.Popen(
    [STREAMLIT, "run", VIEWER, "--server.headless", "false"],
    creationflags=NO_WINDOW,
    cwd=HERE,
)

# Give Streamlit a moment to start, then open the browser.
time.sleep(4)
import webbrowser
webbrowser.open("http://localhost:8501")
