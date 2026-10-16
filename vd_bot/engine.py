"""Mesin utama (BotEngine) yang mengatur State Machine, pemindaian frame,

pelacakan jarum secara real-time, evaluasi trigger hit, dan penanganan hotkey.
"""

import collections
from datetime import datetime
import time
from typing import Optional
import cv2
import keyboard
import mss
import numpy as np

from vd_bot.config import (
    CX,
    CY,
    HARDWARE_LATENCY_SEC,
    IN_X,
    IN_Y,
    MID_X,
    MID_Y,
    MONITOR_ROI,
    OUT_X,
    OUT_Y,
)
from vd_bot.detector import (
    detect_red_needle,
    detect_white_target,
    is_skillcheck_ui_present,
)
from vd_bot.input_controller import precise_sleep, press_space_fast
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
    self.hit_counter: int = 0

    self.frame_buffer = collections.deque(maxlen=10)

  def toggle_pause(self):
    self.bot_active = not self.bot_active
    status = ">>> AKTIF <<<" if self.bot_active else "|| PAUSED ||"
    print(f"\n[STATUS] Bot: {status}")

  def trigger_calib(self):
    self.request_calib = True

  def trigger_exit(self):
    self.request_exit = True

  def reset_state_to_idle(self, reason: Optional[str] = None):
    self.current_state = self.STATE_IDLE
    self.locked_target_angle = None
    self.target_samples.clear()
    self.needle_prev_angle = None
    self.needle_prev_time = None
    self.needle_confirm_count = 0
    self.frame_buffer.clear()
    if reason:
      print(f"[IDLE] {reason}")

  def register_hotkeys(self):
    keyboard.add_hotkey("insert", self.toggle_pause)
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
    print("==========================================================")
    print("   BOT SKILL CHECK VD (MODULAR & HIGH ACCURACY ARCH)     ")
    print("==========================================================")
    print(" Hotkeys:")
    print("  - [INSERT] : Pause / Resume Bot")
    print("  - [X]      : Simpan gambar kalibrasi 'cek_kalibrasi.png'")
    print("  - [O]      : Buka folder capture screenshot terakhir di Explorer")
    print("  - [END]    : Keluar dari program")
    print("----------------------------------------------------------")
    print(" Arsitektur:")
    print("  - Modular: config, input_controller, detector, visualizer, engine")
    print("  - Keamanan: Center UI validation & anti-freeze cooldown timeout")
    print("==========================================================\n")

  def start(self):
    start_gui_thread()
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

        # 2. State: COOLDOWN (Anti-Freeze: hard timeout & cek UI center)
        if self.current_state == self.STATE_COOLDOWN:
          if now < self.cooldown_until:
            time.sleep(0.005)
            continue
          else:
            ui_still_active = is_skillcheck_ui_present(frame)
            if not ui_still_active or now > (self.cooldown_until + 0.35):
              self.reset_state_to_idle("Skill check selesai. Siap menunggu berikutnya...")
            continue

        # 3. Validasi UI Skill Check (Anti-Ghost Click pada Baju/Topi/Darah)
        ui_present = is_skillcheck_ui_present(frame)

        if not ui_present:
          if self.current_state == self.STATE_TRACKING:
            if (now - self.last_ui_seen_time) > 0.15:
              self.reset_state_to_idle()
          time.sleep(0.002)
          continue

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
            print(
                f"[TARGET] Balok putih terdeteksi di:"
                f" {self.locked_target_angle:.1f}° (Lebar:"
                f" {self.locked_target_width:.1f}°)"
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

        # Simpan frame ke rolling buffer untuk debug visualizer
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

          # Kasus A: Jarum sedang mendekati target dalam jarak 35 derajat
          if -35.0 <= signed_err < 0.0:
            dist_remaining = -signed_err
            time_to_hit = dist_remaining / max(150.0, self.needle_speed)

            if time_to_hit <= (HARDWARE_LATENCY_SEC + 0.010):
              should_press = True
              remaining_delay = max(0.0, time_to_hit - HARDWARE_LATENCY_SEC)

          # Kasus B (Fail-Safe Stutter): Jarum sudah di balok putih
          elif 0.0 <= signed_err <= (self.locked_target_width / 2.0 + 1.5):
            should_press = True
            remaining_delay = 0.0

          if should_press:
            self.hit_counter += 1
            hit_moment_time = now
            hit_needle_angle = detected_needle
            hit_target_angle = self.locked_target_angle

            if remaining_delay > 0.001:
              precise_sleep(remaining_delay)

            # EKSEKUSI KLIK SPASI HARDWARE
            press_space_fast()

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

            expected_hit_angle = (
                hit_needle_angle + self.needle_speed * HARDWARE_LATENCY_SEC
            ) % 360
            offset = (expected_hit_angle - hit_target_angle + 180) % 360 - 180

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

            print(
                f"\n[TRIGGER HIT #{self.hit_counter}] >>> SPACE DITEKAN! <<<"
                f" [{eval_str}]"
            )
            print(
                f"  | Target: {hit_target_angle:.1f}° | Jarum saat klik:"
                f" {hit_needle_angle:.1f}°"
            )
            print(
                f"  | Kecepatan Jarum: {self.needle_speed:.1f}°/s | Estimasi"
                f" Offset: {offset:+.2f}°"
            )
            print(f"  | Capture Disimpan: {saved_dir}")
            print(
                "  | [INFO] Preview visual capture telah ditampilkan di"
                " jendela GUI!\n"
            )

            self.current_state = self.STATE_COOLDOWN
            self.cooldown_until = time.perf_counter() + 0.50
            continue

        elapsed = time.perf_counter() - loop_start_time
        if elapsed < 0.003:
          time.sleep(0.001)

    stop_gui_thread()
    print("[INFO] Program selesai. Sampai jumpa!")
