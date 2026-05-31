"""Kill the running Cross-Kart viewer. Double-click to stop it."""

import subprocess
import tkinter as tk
from tkinter import messagebox

PORT = 5000

# Find the PID listening on the viewer port, then kill it.
result = subprocess.run(
    ["netstat", "-ano"],
    capture_output=True, text=True,
)

pids = set()
for line in result.stdout.splitlines():
    if f":{PORT}" in line and "LISTENING" in line:
        parts = line.split()
        if parts:
            pids.add(parts[-1])

root = tk.Tk()
root.withdraw()

if pids:
    for pid in pids:
        subprocess.run(["taskkill", "/f", "/pid", pid], capture_output=True)
    messagebox.showinfo("Cross-Kart", "Viewer stopped.")
else:
    messagebox.showinfo("Cross-Kart", "Viewer was not running.")
