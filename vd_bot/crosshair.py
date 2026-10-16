"""Modul overlay crosshair transparan (titik hijau kecil) untuk mempermudah bidikan pistol.

Menggunakan layered window Win32 transparan dengan flag WS_EX_TRANSPARENT
sehingga klik mouse dan gerakan kamera 100% tembus tanpa ada latency atau gangguan.
"""

import threading
import time
import tkinter as tk
from typing import Optional
import win32con
import win32gui


class CrosshairOverlay:
  """Overlay crosshair titik hijau di tengah layar (click-through & zero lag)."""

  def __init__(
      self,
      x: int = 960,
      y: int = 540,
      radius: int = 2,
      color: str = "#00FF66",
  ):
    self.x = x
    self.y = y
    self.radius = radius
    self.color = color
    self.root: Optional[tk.Tk] = None
    self.visible: bool = True
    self.thread: Optional[threading.Thread] = None

  def _run_gui(self):
    """Loop internal Tkinter yang berjalan di daemon thread terpisah."""
    self.root = tk.Tk()
    self.root.overrideredirect(True)
    self.root.attributes("-topmost", True)
    # Warna #000001 dijadikan transparan total oleh Windows DWM
    self.root.attributes("-transparentcolor", "#000001")
    self.root.config(bg="#000001")

    # Ukuran jendela secukupnya untuk titik + outline hitam
    size = max(16, (self.radius + 4) * 2)
    win_x = int(round(self.x - size / 2.0))
    win_y = int(round(self.y - size / 2.0))
    self.root.geometry(f"{size}x{size}+{win_x}+{win_y}")

    canvas = tk.Canvas(
        self.root,
        width=size,
        height=size,
        bg="#000001",
        highlightthickness=0,
    )
    canvas.pack(fill="both", expand=True)

    cx = size // 2
    cy = size // 2
    r = self.radius

    # Outline hitam 1px agar terlihat jelas saat membidik latar belakang putih/terang
    canvas.create_oval(
        cx - r - 1,
        cy - r - 1,
        cx + r + 1,
        cy + r + 1,
        outline="#000000",
        width=1,
    )
    # Titik hijau neon terang di tengah
    canvas.create_oval(
        cx - r,
        cy - r,
        cx + r,
        cy + r,
        fill=self.color,
        outline=self.color,
    )

    self.root.update()

    # Terapkan styling Win32: Click-Through (WS_EX_TRANSPARENT) & No Taskbar (WS_EX_TOOLWINDOW)
    hwnd = win32gui.GetParent(self.root.winfo_id())
    if hwnd == 0:
      hwnd = self.root.winfo_id()

    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(
        hwnd,
        win32con.GWL_EXSTYLE,
        ex_style
        | win32con.WS_EX_LAYERED
        | win32con.WS_EX_TRANSPARENT
        | win32con.WS_EX_TOOLWINDOW,
    )

    self.root.mainloop()

  def start(self):
    """Memulai thread background overlay crosshair."""
    if self.thread is not None and self.thread.is_alive():
      return
    self.thread = threading.Thread(target=self._run_gui, daemon=True)
    self.thread.start()
    time.sleep(0.05)

  def toggle(self):
    """Mengaktifkan / menyembunyikan titik hijau secara instan."""
    if not self.root:
      return
    self.visible = not self.visible
    if self.visible:
      self.root.after(0, self.root.deiconify)
    else:
      self.root.after(0, self.root.withdraw)

  def stop(self):
    """Menutup jendela crosshair."""
    if self.root:
      self.root.after(0, self.root.destroy)
