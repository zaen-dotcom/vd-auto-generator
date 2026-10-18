"""Modul Auto-Hold Left Mouse Button (LMB).

Mendeteksi double-click kiri cepat untuk menahan klik kiri secara otomatis (berguna
untuk repair generator Violence District tanpa pegal jari).
Tahan klik kiri otomatis dilepas jika pemain menekan tombol gerak (W, A, S, D)
atau menekan klik kiri sekali lagi.
"""

import threading
import time
from typing import Optional
import keyboard
from pynput import mouse

from vd_bot.input_controller import mouse_left_down, mouse_left_up


class MouseHoldController:
  """Mengontrol auto-hold klik kiri mouse berbasis double-click dan auto-release WASD."""

  def __init__(self, enabled: bool = True, double_click_threshold: float = 0.35):
    self.enabled: bool = enabled
    self.double_click_threshold: float = double_click_threshold
    self.is_holding: bool = False
    self.potential_double_click: bool = False
    self.last_click_down_time: float = 0.0
    self.last_click_up_time: float = 0.0
    self.is_simulating: bool = False

    self.listener: Optional[mouse.Listener] = None
    self.keyboard_hook = None
    self._lock = threading.Lock()

  def _on_mouse_click(self, x, y, button, pressed, *args):
    """Callback listener mouse pynput."""
    if not self.enabled:
      return
    if button != mouse.Button.left:
      return

    # Abaikan event yang disintesis/disimulasikan oleh bot
    if self.is_simulating:
      return
    if args and args[0] is True:
      return

    now = time.perf_counter()

    with self._lock:
      if pressed:
        # Klik fisik mouse down
        if self.is_holding:
          # Jika sedang auto-hold dan user klik kiri manual, lepas tahanan
          self.release_hold(reason="Klik kiri manual ditekan kembali")
          self.potential_double_click = False
          return

        time_since_last_down = now - self.last_click_down_time
        if time_since_last_down <= self.double_click_threshold:
          self.potential_double_click = True
        else:
          self.potential_double_click = False

        self.last_click_down_time = now

      else:
        # Klik fisik mouse up
        if self.is_holding:
          return

        time_since_last_up = now - self.last_click_up_time
        self.last_click_up_time = now

        # Jika gesture double-click selesai dilepas
        if (
            self.potential_double_click
            and time_since_last_up <= self.double_click_threshold
        ):
          self.potential_double_click = False
          self.activate_hold()

  def _on_key_press(self, event):
    """Callback tombol keyboard untuk auto-release saat bergerak."""
    if not self.is_holding:
      return
    key_name = getattr(event, "name", "")
    if not key_name:
      return
    key = key_name.lower()
    # Deteksi tombol gerak WASD dan tanda panah navigasi
    if key in ("w", "a", "s", "d", "up", "down", "left", "right"):
      with self._lock:
        if self.is_holding:
          self.release_hold(reason=f"Tombol gerak '{key.upper()}' ditekan")

  def activate_hold(self):
    """Mengaktifkan tahanan klik kiri secara otomatis."""
    if self.is_holding:
      return
    self.is_holding = True
    self.is_simulating = True
    try:
      mouse_left_down()
    finally:
      time.sleep(0.02)
      self.is_simulating = False
    print("\n[AUTO-HOLD LMB] >>> KLIK KIRI DITAHAN OTOMATIS! <<<")
    print("  * Status   : Menahan klik kiri untuk repair generator...")
    print(
        "  * Pelepasan: Tekan WASD untuk bergerak, atau Klik Kiri sekali"
        " lagi.\n"
    )

  def release_hold(self, reason: str = ""):
    """Melepaskan tahanan klik kiri."""
    if not self.is_holding:
      return
    self.is_holding = False
    self.is_simulating = True
    try:
      mouse_left_up()
    finally:
      time.sleep(0.02)
      self.is_simulating = False
    if reason:
      print(f"[AUTO-HOLD LMB] Tahan klik kiri DILEPAS ({reason})")
    else:
      print("[AUTO-HOLD LMB] Tahan klik kiri DILEPAS")

  def toggle(self):
    """Toggle fitur auto-hold aktif/nonaktif."""
    self.enabled = not self.enabled
    if not self.enabled and self.is_holding:
      self.release_hold(reason="Fitur dinonaktifkan")
    status = (
        "ON (Aktif - Double click kiri tahan, WASD lepas)"
        if self.enabled
        else "OFF (Nonaktif)"
    )
    print(f"\n[AUTO-HOLD LMB] Fitur: {status}")

  def start(self):
    """Memulai listener mouse dan keyboard."""
    if self.listener is None:
      self.listener = mouse.Listener(on_click=self._on_mouse_click)
      self.listener.daemon = True
      self.listener.start()
    if self.keyboard_hook is None:
      self.keyboard_hook = keyboard.on_press(self._on_key_press)

  def stop(self):
    """Menghentikan controller dan melepaskan tahanan."""
    if self.is_holding:
      self.release_hold(reason="Bot berhenti")
    if self.listener:
      try:
        self.listener.stop()
      except Exception:
        pass
      self.listener = None
    if self.keyboard_hook:
      try:
        keyboard.unhook(self.keyboard_hook)
      except Exception:
        pass
      self.keyboard_hook = None
