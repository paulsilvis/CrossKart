"""Kill the running Cross-Kart viewer. Double-click to stop it."""

import subprocess
import tkinter as tk
from tkinter import messagebox

result = subprocess.run(
    ["taskkill", "/f", "/im", "streamlit.exe"],
    capture_output=True,
)

root = tk.Tk()
root.withdraw()
if result.returncode == 0:
    messagebox.showinfo("Cross-Kart", "Viewer stopped.")
else:
    messagebox.showinfo("Cross-Kart", "Viewer was not running.")
