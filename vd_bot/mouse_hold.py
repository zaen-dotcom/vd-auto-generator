"""Modul Auto-Hold Left Mouse Button (LMB).

Menahan klik kiri mouse secara otomatis untuk repair generator di Violence District.
Shortcut pemicu:
  - Tombol Keyboard: [G] (default, dapat diatur di config.py)
  - Tombol Mouse   : [Klik Tengah / Scroll Click] dan [Mouse 4 / Mouse 5] (jika tersedia)
Pelepasan otomatis:
  - Tombol gerak karakter: [W], [A], [S], [D] (atau tombol panah)
  - Menekan shortcut pemicu sekali lagi
"""

import ctypes
import threading
import time
from typing import Optional
import keyboard

from vd_bot.input_controller import mouse_left_down, mouse_left_up


class MouseHoldController:
  """Mengontrol auto-hold klik kiri mouse untuk repair generator.

  Mendukung shortcut tombol keyboard (default 'G') dan mouse (Klik Tengah / M4 / M5).
  Otomatis melepas tahan klik kiri saat pemain menekan tombol gerak (W, A, S, D).
  """

  def __init__(
      self,
      enabled: bool = True,
      keyboard_hotkey: str = "g",
      enable_mouse_shortcuts: bool = True,
  ):
    self.enabled: bool = enabled
    self.keyboard_hotkey: str = keyboard_hotkey.lower()
    self.enable_mouse_shortcuts: bool = enable_mouse_shortcuts
    self.is_holding: bool = False

    self._stop_event = threading.Event()
    self._mouse_thread: Optional[threading.Thread] = None
    self.keyboard_hook = None
    self._lock = threading.Lock()

  def toggle_hold(self, source: str = ""):
    """Toggle status tahan klik kiri: aktifkan jika idle, lepaskan jika sedang tahan."""
    if not self.enabled:
      return
    with self._lock:
      if not self.is_holding:
        self.activate_hold(source=source)
      else:
        reason = (
            f"Shortcut {source} ditekan kembali"
            if source
            else "Shortcut ditekan kembali"
        )
        self.release_hold(reason=reason)

  def activate_hold(self, source: str = ""):
    """Mengaktifkan tahanan klik kiri secara hardware."""
    if self.is_holding:
      return
    self.is_holding = True
    mouse_left_down()
    src_str = f" via {source}" if source else ""
    print(f"\n[AUTO-HOLD LMB] >>> KLIK KIRI DITAHAN! <<<{src_str}")
    print("  * Status   : Menahan klik kiri untuk repair generator...")
    print(
        f"  * Pelepasan: Tekan WASD untuk bergerak, atau [{self.keyboard_hotkey.upper()}] / Klik Tengah lagi.\n"
    )

  def release_hold(self, reason: str = ""):
    """Melepaskan tahanan klik kiri."""
    if not self.is_holding:
      return
    self.is_holding = False
    mouse_left_up()
    if reason:
      print(f"[AUTO-HOLD LMB] Tahan klik kiri DILEPAS ({reason})")
    else:
      print("[AUTO-HOLD LMB] Tahan klik kiri DILEPAS")

  def toggle_enabled(self):
    """Toggle fitur auto-hold aktif/nonaktif."""
    self.enabled = not self.enabled
    if not self.enabled and self.is_holding:
      self.release_hold(reason="Fitur dinonaktifkan")
    status = (
        f"ON (Aktif - Tekan [{self.keyboard_hotkey.upper()}] / Klik Tengah Tahan, WASD Lepas)"
        if self.enabled
        else "OFF (Nonaktif)"
    )
    print(f"\n[AUTO-HOLD LMB] Fitur: {status}")

  def _on_key_press(self, event):
    """Callback hook keyboard untuk aktivasi shortcut dan auto-release WASD."""
    if not self.enabled:
      return
    key_name = getattr(event, "name", "")
    if not key_name:
      return
    key = key_name.lower()

    # 1. Cek apakah ini tombol aktivasi keyboard (misal 'g')
    if key == self.keyboard_hotkey:
      self.toggle_hold(source=f"Tombol '{self.keyboard_hotkey.upper()}'")
      return

    # 2. Cek apakah ini tombol gerak WASD / Panah untuk auto-release
    if self.is_holding and key in (
        "w",
        "a",
        "s",
        "d",
        "up",
        "down",
        "left",
        "right",
    ):
      with self._lock:
        if self.is_holding:
          self.release_hold(reason=f"Tombol gerak '{key.upper()}' ditekan")

  def _mouse_poll_loop(self):
    """Thread ringan untuk memantau Klik Tengah Mouse (Scroll Click) & Tombol Samping (M4/M5)."""
    last_mbutton = False
    last_x1 = False
    last_x2 = False

    while not self._stop_event.is_set():
      if not self.enabled or not self.enable_mouse_shortcuts:
        time.sleep(0.05)
        continue

      try:
        # VK_MBUTTON = 0x04 (Klik Tengah / Scroll Click)
        mbutton = (ctypes.windll.user32.GetAsyncKeyState(0x04) & 0x8000) != 0
        # VK_XBUTTON1 = 0x05 (Mouse 4)
        x1 = (ctypes.windll.user32.GetAsyncKeyState(0x05) & 0x8000) != 0
        # VK_XBUTTON2 = 0x06 (Mouse 5)
        x2 = (ctypes.windll.user32.GetAsyncKeyState(0x06) & 0x8000) != 0

        # Deteksi event saat baru ditekan (rising edge)
        if mbutton and not last_mbutton:
          self.toggle_hold(source="Klik Tengah Mouse")
        elif x1 and not last_x1:
          self.toggle_hold(source="Tombol Samping Mouse (M4)")
        elif x2 and not last_x2:
          self.toggle_hold(source="Tombol Samping Mouse (M5)")

        last_mbutton = mbutton
        last_x1 = x1
        last_x2 = x2
      except Exception:
        pass

      time.sleep(0.01)  # 100 Hz, 0% CPU

  def start(self):
    """Memulai listener keyboard dan thread polling mouse."""
    if self.keyboard_hook is None:
      self.keyboard_hook = keyboard.on_press(self._on_key_press)
    if self.enable_mouse_shortcuts and (
        self._mouse_thread is None or not self._mouse_thread.is_alive()
    ):
      self._stop_event.clear()
      self._mouse_thread = threading.Thread(
          target=self._mouse_poll_loop, daemon=True
      )
      self._mouse_thread.start()

  def stop(self):
    """Menghentikan controller dan melepaskan tahanan."""
    if self.is_holding:
      self.release_hold(reason="Bot berhenti")
    self._stop_event.set()
    if self.keyboard_hook:
      try:
        keyboard.unhook(self.keyboard_hook)
      except Exception:
        pass
      self.keyboard_hook = None
    self._mouse_thread = None
