"""Modul kontrol input perangkat keras langsung (Direct Hardware Scancode)

dan high-precision sleep via Windows API.
"""

import ctypes
import time

try:
  ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
  pass

SendInput = ctypes.windll.user32.SendInput
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
  _fields_ = [
      ("wVk", ctypes.c_ushort),
      ("wScan", ctypes.c_ushort),
      ("dwFlags", ctypes.c_ulong),
      ("time", ctypes.c_ulong),
      ("dwExtraInfo", PUL),
  ]


class HardwareInput(ctypes.Structure):
  _fields_ = [
      ("uMsg", ctypes.c_ulong),
      ("wParamL", ctypes.c_short),
      ("wParamH", ctypes.c_ushort),
  ]


class MouseInput(ctypes.Structure):
  _fields_ = [
      ("dx", ctypes.c_long),
      ("dy", ctypes.c_long),
      ("mouseData", ctypes.c_ulong),
      ("dwFlags", ctypes.c_ulong),
      ("time", ctypes.c_ulong),
      ("dwExtraInfo", PUL),
  ]


class Input_I(ctypes.Union):
  _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]


class Input(ctypes.Structure):
  _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]


extra = ctypes.c_ulong(0)
# DIK_SPACE: wVk = 0x20, wScan = 0x39
ii_down = Input_I()
ii_down.ki = KeyBdInput(0x20, 0x39, 0x0008, 0, ctypes.pointer(extra))
x_down = Input(ctypes.c_ulong(1), ii_down)

ii_up = Input_I()
ii_up.ki = KeyBdInput(0x20, 0x39, 0x0008 | 0x0002, 0, ctypes.pointer(extra))
x_up = Input(ctypes.c_ulong(1), ii_up)


def press_space_fast():
  """Mengirimkan event Space hardware secepat mungkin (hold ~35ms)."""
  SendInput(1, ctypes.pointer(x_down), ctypes.sizeof(x_down))
  time.sleep(0.035)
  SendInput(1, ctypes.pointer(x_up), ctypes.sizeof(x_up))


# Input definitions untuk Left Mouse Button (LMB)
extra_mouse = ctypes.c_ulong(0)

# MOUSEEVENTF_LEFTDOWN = 0x0002
mi_l_down = Input_I()
mi_l_down.mi = MouseInput(0, 0, 0, 0x0002, 0, ctypes.pointer(extra_mouse))
mouse_l_down_input = Input(ctypes.c_ulong(0), mi_l_down)

# MOUSEEVENTF_LEFTUP = 0x0004
mi_l_up = Input_I()
mi_l_up.mi = MouseInput(0, 0, 0, 0x0004, 0, ctypes.pointer(extra_mouse))
mouse_l_up_input = Input(ctypes.c_ulong(0), mi_l_up)


def mouse_left_down():
  """Mengirimkan event Left Mouse Down (tekan tahan tombol kiri mouse)."""
  SendInput(1, ctypes.pointer(mouse_l_down_input), ctypes.sizeof(mouse_l_down_input))
  try:
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
  except Exception:
    pass


def mouse_left_up():
  """Mengirimkan event Left Mouse Up (lepas tombol kiri mouse)."""
  SendInput(1, ctypes.pointer(mouse_l_up_input), ctypes.sizeof(mouse_l_up_input))
  try:
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
  except Exception:
    pass


def precise_sleep(seconds: float):
  """High-precision sleep untuk micro-delay sub-frame di Windows."""
  if seconds <= 0:
    return
  target = time.perf_counter() + seconds
  if seconds > 0.003:
    time.sleep(seconds - 0.002)
  while time.perf_counter() < target:
    pass

