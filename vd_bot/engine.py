"""Mesin utama (BotEngine) yang mengatur State Machine, pemindaian frame,

pelacakan jarum secara real-time, evaluasi trigger hit, dan penanganan hotkey.
"""

import collections
from datetime import datetime
import gc
import time
from typing import Optional
import cv2
import keyboard
import mss
import numpy as np

from vd_bot.config import (
    CROSSHAIR_COLOR,
    CROSSHAIR_RADIUS,
    CROSSHAIR_X,
    CROSSHAIR_Y,
    CX,
    CY,
    DOUBLE_CLICK_THRESHOLD,
    ENABLE_AUTO_HOLD_LMB,
    ENABLE_CROSSHAIR,
    ENABLE_DEBUG_CAPTURES,
    HARDWARE_LATENCY_SEC,
    IN_X,
    IN_Y,
    MID_X,
    MID_Y,
    MONITOR_ROI,
    OUT_X,
    OUT_Y,
    R_MID,
    SCREEN_CENTER_X,
    SCREEN_CENTER_Y,
)
from vd_bot.crosshair import CrosshairOverlay
from vd_bot.detector import (
    detect_red_needle,
    detect_white_target,
    is_skillcheck_ui_present,
)
from vd_bot.input_controller import precise_sleep, press_space_fast
from vd_bot.mouse_hold import MouseHoldController
from vd_bot.math_utils import (
    circular_mean_angle,
    clockwise_distance,
    get_signed_angle_diff,
)
from vd_bot.visualizer import (
    build_and_save_debug_package,
    open_capture_folder,
    start_gui_thread,
    stop_gui_thread,
)


class BotEngine:
  """Engine otomatisasi Skill Check Violence District."""

  STATE_IDLE = "IDLE"
  STATE_TRACKING = "TRACKING"
  STATE_COOLDOWN = "COOLDOWN"

  def __init__(self):
    self.bot_active: bool = True
    self.request_calib: bool = False
    self.request_exit: bool = False

    self.enable_debug_captures: bool = ENABLE_DEBUG_CAPTURES
    self.ui_active_logged: bool = False

    self.crosshair: Optional[CrosshairOverlay] = (
        CrosshairOverlay(
            x=CROSSHAIR_X,
            y=CROSSHAIR_Y,
            radius=CROSSHAIR_RADIUS,
            color=CROSSHAIR_COLOR,
        )
        if ENABLE_CROSSHAIR
        else None
    )

    self.mouse_hold: Optional[MouseHoldController] = (
        MouseHoldController(
            enabled=ENABLE_AUTO_HOLD_LMB,
            double_click_threshold=DOUBLE_CLICK_THRESHOLD,
        )
        if ENABLE_AUTO_HOLD_LMB
        else None
    )

    self.crosshair_presets = [
        {
            "name": "Preset 1: Populer VD (Offset X=-4, Y=+10)",
            "x": SCREEN_CENTER_X - 4,
            "y": SCREEN_CENTER_Y + 10,
        },
        {
            "name": "Preset 2: Lebih Kiri VD (Offset X=-20, Y=+10)",
            "x": SCREEN_CENTER_X - 20,
            "y": SCREEN_CENTER_Y + 10,
        },
        {
            "name": "Preset 3: Pusat Layar Murni (Offset X=0, Y=0)",
            "x": SCREEN_CENTER_X,
            "y": SCREEN_CENTER_Y,
        },
    ]
    self.current_crosshair_preset_idx = 0

    self.current_state: str = self.STATE_IDLE
    self.locked_target_angle: Optional[float] = None
    self.locked_target_width: float = 6.0
    self.target_samples: list = []

    self.needle_prev_angle: Optional[float] = None
    self.needle_prev_time: Optional[float] = None
    self.needle_speed: float = 300.0
    self.needle_confirm_count: int = 0
    self.last_ui_seen_time: float = 0.0
    self.cooldown_until: float = 0.0
    self.last_hit_target_angle: Optional[float] = None
    self.last_hit_time: float = 0.0
    self.hit_counter: int = 0

    self.frame_buffer = collections.deque(maxlen=10)

  def toggle_pause(self):
    self.bot_active = not self.bot_active
    status = ">>> AKTIF <<<" if self.bot_active else "|| PAUSED ||"
    print(f"\n[STATUS] Bot: {status}")
    if not self.bot_active and self.mouse_hold and self.mouse_hold.is_holding:
      self.mouse_hold.release_hold(reason="Bot di-pause")

  def trigger_calib(self):
    self.request_calib = True

  def trigger_exit(self):
    self.request_exit = True
    if self.mouse_hold:
      self.mouse_hold.stop()

  def reset_state_to_idle(self, reason: Optional[str] = None):
    self.current_state = self.STATE_IDLE
    self.locked_target_angle = None
    self.target_samples.clear()
    self.needle_prev_angle = None
    self.needle_prev_time = None
    self.needle_confirm_count = 0
    self.last_hit_target_angle = None
    self.ui_active_logged = False
    self.frame_buffer.clear()
    gc.enable()
    if reason:
      print(f"[IDLE] {reason}")

  def toggle_debug_captures(self):
    self.enable_debug_captures = not self.enable_debug_captures
    if self.enable_debug_captures:
      start_gui_thread()
      status = "ON (Aktif - Menyimpan foto & menampilkan GUI visualizer)"
    else:
      stop_gui_thread()
      status = "OFF (Nonaktif - Hemat disk & performa maksimal)"
    print(f"\n[DEBUG CAPTURES] Status: {status}")

  def toggle_crosshair(self):
    if self.crosshair:
      self.crosshair.toggle()
      status = "ON (Aktif)" if self.crosshair.visible else "OFF (Disembunyikan)"
      print(f"\n[CROSSHAIR] Titik Hijau: {status}")

  def cycle_crosshair_preset(self):
    if not self.crosshair:
      return
    self.current_crosshair_preset_idx = (
        self.current_crosshair_preset_idx + 1
    ) % len(self.crosshair_presets)
    preset = self.crosshair_presets[self.current_crosshair_preset_idx]
    self.crosshair.set_position(preset["x"], preset["y"])
    print(
        f"\n[CROSSHAIR PRESET] Ganti ke -> {preset['name']} | Koordinat: ({preset['x']}, {preset['y']})"
    )

  def toggle_mouse_hold(self):
    if self.mouse_hold:
      self.mouse_hold.toggle()

  def register_hotkeys(self):
    keyboard.add_hotkey("insert", self.toggle_pause)
    keyboard.add_hotkey("f7", self.toggle_debug_captures)
    keyboard.add_hotkey("f6", self.toggle_crosshair)
    keyboard.add_hotkey("f8", self.cycle_crosshair_preset)
    keyboard.add_hotkey("f9", self.toggle_mouse_hold)
    keyboard.add_hotkey("x", self.trigger_calib)
    keyboard.add_hotkey("o", open_capture_folder)
    keyboard.add_hotkey("end", self.trigger_exit)

  def save_calibration_preview(self, frame: np.ndarray, timestamp: float):
    preview = frame[:, :, :3].copy()
    for x, y in zip(IN_X, IN_Y):
      preview[y, x] = [255, 255, 0]  # Cyan
    for x, y in zip(MID_X, MID_Y):
      preview[y, x] = [0, 255, 0]  # Green
    for x, y in zip(OUT_X, OUT_Y):
      preview[y, x] = [0, 165, 255]  # Orange
    cv2.drawMarker(
        preview,
        (CX, CY),
        (0, 0, 255),
        markerType=cv2.MARKER_CROSS,
        markerSize=10,
        thickness=1,
    )
    cv2.imwrite("cek_kalibrasi.png", preview)
    print(
        f"[INFO] Kalibrasi disimpan ke 'cek_kalibrasi.png' pada {timestamp:.2f}"
    )

  def print_banner(self):
    captures_text = (
        "ON (Aktif - Tekan 'F7' untuk Matikan)"
        if self.enable_debug_captures
        else "OFF (Nonaktif - Tekan 'F7' untuk Aktifkan)"
    )
    active_preset = (
        self.crosshair_presets[self.current_crosshair_preset_idx]["name"]
        if self.crosshair
        else ""
    )
    crosshair_text = (
        f"ON ({active_preset} - Tekan 'F6' Matikan / 'F8' Ganti Preset)"
        if (self.crosshair and self.crosshair.visible)
        else "OFF (Nonaktif - Tekan 'F6' untuk Aktifkan)"
    )
    hold_text = (
        "ON (Aktif - Tekan 'F9' untuk Matikan)"
        if (self.mouse_hold and self.mouse_hold.enabled)
        else "OFF (Nonaktif - Tekan 'F9' untuk Aktifkan)"
    )
    print("==========================================================")
    print("   BOT SKILL CHECK VD (MODULAR & HIGH ACCURACY ARCH)     ")
    print(f"  - Debug Captures  : {captures_text}")
    print(f"  - Crosshair Pistol: {crosshair_text}")
    print(f"  - Auto-Hold LMB   : {hold_text}")
    print("----------------------------------------------------------")
    print(" Kontrol Hotkey:")
    print("  - [F7]     : Toggle Debug Captures & GUI (On/Off - Default OFF)")
    print("  - [F6]     : Toggle Crosshair Pistol (On/Off)")
    print("  - [F8]     : Ganti Preset Crosshair (X=-4, Y=10 <-> X=-20, Y=10)")
    print("  - [F9]     : Toggle Auto-Hold LMB (On/Off - Double-Click Tahan, WASD Lepas)")
    print("  - [Insert] : Pause / Resume Bot")
    print("  - [O]      : Buka Folder Hasil Debug Captures di Explorer")
    print("  - [X]      : Snapshot Kalibrasi Lingkaran (cek_kalibrasi.png)")
    print("  - [End]    : Keluar dari Bot")
    print("==========================================================\n")

  def start(self):
    if self.enable_debug_captures:
      start_gui_thread()
    if self.crosshair:
      self.crosshair.start()
    if self.mouse_hold:
      self.mouse_hold.start()
    self.register_hotkeys()
    self.print_banner()

    with mss.mss() as sct:
      print("[READY] Bot aktif & siap memantau skill check (150+ FPS)...\n")

      while not self.request_exit:
        loop_start_time = time.perf_counter()

        if not self.bot_active:
          time.sleep(0.03)
          continue

        # 1. Grab Frame dari Monitor ROI
        frame = np.array(sct.grab(MONITOR_ROI))
        now = time.perf_counter()

        # Fitur Kalibrasi Snapshot [X]
        if self.request_calib:
          self.save_calibration_preview(frame, now)
          self.request_calib = False

        # 2. State: COOLDOWN (Anti-Double-Click & Deteksi Combo Killer Perk Tanpa Jeda)
        if self.current_state == self.STATE_COOLDOWN:
          if now < self.cooldown_until:
            time.sleep(0.002)
            continue

          ui_still_active = is_skillcheck_ui_present(frame)
          if not ui_still_active:
            self.reset_state_to_idle("Skill check selesai. Siap menunggu berikutnya...")
            continue

          # UI masih aktif di layar! Cek apakah balok putih baru sudah muncul
          detected_target, target_w = detect_white_target(frame)
          if detected_target is None:
            # Balok putih lama sudah hilang/fading
            self.last_hit_target_angle = None
            if (now - self.last_hit_time) > 0.35:
              self.reset_state_to_idle()
            continue

          # Ada balok putih terdeteksi. Cek apakah ini target baru (Combo Perk)
          is_new_target = False
          if self.last_hit_target_angle is None:
            is_new_target = True
          else:
            diff = abs((detected_target - self.last_hit_target_angle + 180) % 360 - 180)
            if diff > 12.0:
              is_new_target = True

          if is_new_target:
            # Skill check berikutnya langsung muncul tanpa jeda!
            self.target_samples = [detected_target]
            self.locked_target_angle = detected_target
            self.locked_target_width = max(4.0, target_w)
            self.needle_prev_angle = None
            self.needle_prev_time = None
            self.needle_confirm_count = 0
            self.current_state = self.STATE_TRACKING
            gc.disable()
            print(
                f"\n[COMBO PERK] Skill check baru terdeteksi di:"
                f" {self.locked_target_angle:.1f}°! Mengunci target..."
            )
            continue
          else:
            # Masih balok putih lama yang sedang fading out, tunggu sampai hilang
            if (now - self.last_hit_time) > 0.35:
              self.reset_state_to_idle()
            continue

        # 3. Validasi UI Skill Check (Anti-Ghost Click pada Baju/Topi/Darah)
        ui_present = is_skillcheck_ui_present(frame)

        if not ui_present:
          self.ui_active_logged = False
          if self.current_state == self.STATE_TRACKING:
            if (now - self.last_ui_seen_time) > 0.15:
              self.reset_state_to_idle()
          time.sleep(0.002)
          continue

        if not self.ui_active_logged:
          print(f"\n[UI DETECTED] Skill check aktif di layar! (Container gelap & ikon [_] valid)")
          self.ui_active_logged = True

        self.last_ui_seen_time = now

        # 4. Deteksi Target Putih & Jarum Merah
        detected_target, target_w = detect_white_target(frame)
        detected_needle, needle_w = detect_red_needle(
            frame, prev_angle=self.needle_prev_angle
        )

        # 5. Kunci & Perhalus Sudut Target Putih
        if detected_target is not None:
          if self.locked_target_angle is None:
            self.target_samples = [detected_target]
            self.locked_target_angle = detected_target
            self.locked_target_width = max(4.0, target_w)
            self.current_state = self.STATE_TRACKING
            gc.disable()  # Pause GC saat jarum berputar agar deterministik tanpa micro-stutter
            print(
                f"[TARGET LOCKED] Balok putih terkunci di:"
                f" {self.locked_target_angle:.1f}° | Lebar: {self.locked_target_width:.1f}° | R_MID: {R_MID}px"
            )
          else:
            signed_dist = (
                get_signed_angle_diff(detected_needle, self.locked_target_angle)
                if detected_needle is not None
                else -100.0
            )
            if signed_dist < -25.0 and len(self.target_samples) < 5:
              self.target_samples.append(detected_target)
              self.locked_target_angle = circular_mean_angle(
                  self.target_samples
              )

        # 6. Pelacakan Jarum & Kecepatan
        cw_dist = None
        if detected_needle is not None:
          if (
              self.needle_prev_angle is not None
              and self.needle_prev_time is not None
          ):
            dt = now - self.needle_prev_time
            if dt > 0:
              d_theta = (detected_needle - self.needle_prev_angle) % 360
              if 0.2 <= d_theta <= 40.0:
                inst_speed = d_theta / dt
                if 120.0 <= inst_speed <= 650.0:
                  self.needle_confirm_count += 1
                  self.needle_speed = (
                      0.65 * self.needle_speed + 0.35 * inst_speed
                  )
              elif d_theta < 0.2:
                self.needle_confirm_count = max(0, self.needle_confirm_count - 1)

          self.needle_prev_angle = detected_needle
          self.needle_prev_time = now

          if self.locked_target_angle is not None:
            cw_dist = clockwise_distance(
                self.locked_target_angle, detected_needle
            )

        # Simpan frame ke rolling buffer hanya jika debug visualizer diaktifkan
        if self.enable_debug_captures:
          self.frame_buffer.append({
              "img": frame,
              "time": now,
              "needle_angle": detected_needle,
              "target_angle": self.locked_target_angle,
              "dist": cw_dist,
              "speed": self.needle_speed,
          })

        # 7. Evaluasi Trigger Eksekusi Spasi (Predictive Lead + Stutter Fail-Safe)
        if self.locked_target_angle is not None and detected_needle is not None:
          signed_err = get_signed_angle_diff(
              detected_needle, self.locked_target_angle
          )
          should_press = False
          remaining_delay = 0.0
          trigger_mode = "UNKNOWN"

          # Kasus A: Jarum sedang mendekati target dalam jarak 35 derajat
          if -35.0 <= signed_err < 0.0:
            dist_remaining = -signed_err
            time_to_hit = dist_remaining / max(150.0, self.needle_speed)

            if time_to_hit <= (HARDWARE_LATENCY_SEC + 0.010):
              should_press = True
              remaining_delay = max(0.0, time_to_hit - HARDWARE_LATENCY_SEC)
              trigger_mode = "PREDICTIVE_LEAD (Mendekati target)"

          # Kasus B (Fail-Safe Stutter): Jarum sudah di balok putih
          elif 0.0 <= signed_err <= (self.locked_target_width / 2.0 + 1.5):
            should_press = True
            remaining_delay = 0.0
            trigger_mode = "FAILSAFE_INSIDE (Jarum di balok putih)"

          if should_press:
            self.hit_counter += 1
            hit_moment_time = now
            hit_needle_angle = detected_needle
            hit_target_angle = self.locked_target_angle

            if remaining_delay > 0.001:
              precise_sleep(remaining_delay)

            # EKSEKUSI KLIK SPASI HARDWARE (INSTAN)
            press_space_fast()

            lead_deg = self.needle_speed * HARDWARE_LATENCY_SEC
            expected_hit_angle = (hit_needle_angle + lead_deg) % 360
            offset = (expected_hit_angle - hit_target_angle + 180) % 360 - 180

            eval_str = (
                "PERFECT HIT (SEMPURNA!)"
                if abs(offset) <= 3.5
                else ("GOOD HIT" if abs(offset) <= 6.5 else ("MISS (TERLALU CEPAT)" if offset < -6.5 else "MISS (TERLAMBAT)"))
            )

            print("\n" + "=" * 64)
            print(f"[TRIGGER HIT #{self.hit_counter}] >>> SPACE DITEKAN! <<< [{eval_str}]")
            print("-" * 64)
            print(f"  * Mode Trigger        : {trigger_mode}")
            print(f"  * Posisi Target       : {hit_target_angle:.1f}° (Lebar: {self.locked_target_width:.1f}°)")
            print(f"  * Posisi Jarum        : {hit_needle_angle:.1f}° (Sisa jarak: {abs(signed_err):.1f}°)")
            print(f"  * Kecepatan Jarum     : {self.needle_speed:.1f}°/s | Lead Kompensasi: {lead_deg:.2f}°")
            print(f"  * Hardware Latency    : {HARDWARE_LATENCY_SEC*1000:.1f}ms | Micro-Delay: {remaining_delay*1000:.1f}ms")
            print(f"  * Estimasi Kontak     : {expected_hit_angle:.1f}° -> Offset Deviasi: {offset:+.2f}°")
            print(f"  * Evaluasi Ketepatan  : {eval_str}")

            # Simpan paket capture visual hanya jika fitur debug diaktifkan
            if self.enable_debug_captures:
              hit_record = {
                  "img": frame,
                  "time": hit_moment_time,
                  "needle_angle": hit_needle_angle,
                  "target_angle": hit_target_angle,
                  "dist": cw_dist,
                  "speed": self.needle_speed,
              }

              post_records = []
              for _ in range(2):
                time.sleep(0.025)
                p_frame = np.array(sct.grab(MONITOR_ROI))
                p_time = time.perf_counter()
                p_needle, _ = detect_red_needle(p_frame)
                post_records.append({
                    "img": p_frame,
                    "time": p_time,
                    "needle_angle": p_needle,
                    "target_angle": hit_target_angle,
                    "dist": (
                        clockwise_distance(hit_target_angle, p_needle)
                        if p_needle
                        else None
                    ),
                })

              pre_records = (
                  list(self.frame_buffer)[-5:-1]
                  if len(self.frame_buffer) >= 5
                  else list(self.frame_buffer)[:-1]
              )

              stats = {
                  "hit_count": self.hit_counter,
                  "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:12],
                  "target_deg": hit_target_angle,
                  "needle_deg": hit_needle_angle,
                  "offset_deg": offset,
                  "speed_deg_s": self.needle_speed,
              }

              saved_dir, montage_file, eval_str = build_and_save_debug_package(
                  pre_records, hit_record, post_records, stats
              )

              print(f"  * Debug Captures      : DISIMPAN di {saved_dir}")
              print("  * GUI Viewer          : Preview montage tampil di layar")
            else:
              print("  * Debug Captures      : OFF (Tekan F7 untuk merekam frame foto jika diperlukan)")
            print("=" * 64 + "\n")

            self.last_hit_target_angle = hit_target_angle
            self.last_hit_time = hit_moment_time
            self.current_state = self.STATE_COOLDOWN
            gc.enable()  # Re-enable GC saat cooldown
            self.cooldown_until = time.perf_counter() + 0.08  # 80ms refractory anti-double-click
            self.locked_target_angle = None
            self.target_samples.clear()
            self.needle_prev_angle = None
            self.needle_confirm_count = 0
            continue

        elapsed = time.perf_counter() - loop_start_time
        if elapsed < 0.003:
          time.sleep(0.001)

    if ENABLE_DEBUG_CAPTURES:
      stop_gui_thread()
    if self.crosshair:
      self.crosshair.stop()
    print("[INFO] Program selesai. Sampai jumpa!")
