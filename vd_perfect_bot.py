import collections
import ctypes
from datetime import datetime
import os
import queue
import threading
import time
import cv2
import keyboard
import mss
import numpy as np

# =====================================================================
# 0. DIRECT WINDOWS HARDWARE SCANCODE INPUT & HIGH-PRECISION TIMER
# =====================================================================
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


def precise_sleep(seconds):
  """High-precision sleep untuk micro-delay sub-frame di Windows."""
  if seconds <= 0:
    return
  target = time.perf_counter() + seconds
  if seconds > 0.003:
    time.sleep(seconds - 0.002)
  while time.perf_counter() < target:
    pass


# =====================================================================
# 1. KONFIGURASI KALIBRASI & TIMING
# =====================================================================
CENTER_X = 959
CENTER_Y = 566
R_MID = 66
R_IN = R_MID - 3  # 63 px
R_OUT = R_MID + 3  # 69 px

# Estimasi latency hardware + input buffer (dalam detik)
HARDWARE_LATENCY_SEC = 0.016

PADDING = 20
HALF_BOX = R_OUT + PADDING  # 89 px

monitor_roi = {
    "top": CENTER_Y - HALF_BOX,
    "left": CENTER_X - HALF_BOX,
    "width": HALF_BOX * 2,
    "height": HALF_BOX * 2,
}

angles_deg = np.arange(360)
angles_rad = np.deg2rad(angles_deg)
cx, cy = HALF_BOX, HALF_BOX


def create_ring_coords(radius):
  rx = np.round(cx + radius * np.cos(angles_rad)).astype(int)
  ry = np.round(cy + radius * np.sin(angles_rad)).astype(int)
  return rx, ry


# Radius sensor untuk balok putih (Perfect Target Zone)
target_radii = [R_MID - 2, R_MID - 1, R_MID, R_MID + 1, R_MID + 2]
target_coords = [create_ring_coords(r) for r in target_radii]

# Radius sensor untuk jarum merah (Needle Tracking)
needle_radii = [R_MID - 6, R_MID - 11, R_MID - 16, R_MID - 21, R_MID - 26]
needle_coords = [create_ring_coords(r) for r in needle_radii]

# Cincin preview kalibrasi
in_x, in_y = create_ring_coords(R_IN)
mid_x, mid_y = create_ring_coords(R_MID)
out_x, out_y = create_ring_coords(R_OUT)


# =====================================================================
# 2. HELPER MATEMATIKA SUDUT & CLUSTERING
# =====================================================================
def circular_mean_angle(deg_array):
  """Menghitung sudut rata-rata sirkular dalam derajat [0, 360)."""
  rads = np.deg2rad(deg_array)
  mean_rad = np.arctan2(np.mean(np.sin(rads)), np.mean(np.cos(rads)))
  return np.rad2deg(mean_rad) % 360


def clockwise_distance(target, current):
  """Jarak tempuh searah jarum jam (clockwise) dari current menuju target."""
  return (target - current) % 360


def get_signed_angle_diff(needle, target):
  """Selisih sudut bertanda dari target ke needle dalam rentang [-180, 180].

  Negatif: jarum berada sebelum target (sedang mendekati). Positif: jarum sudah
  melewati target.
  """
  return (needle - target + 180) % 360 - 180


def find_circular_clusters(active_indices, max_gap=2):
  """Mengelompokkan indeks sudut yang berdekatan menjadi cluster contiguous,

  dengan menangani wrap-around pada titik 359 -> 0 derajat.
  """
  if len(active_indices) == 0:
    return []
  sorted_idx = np.sort(np.unique(active_indices))
  if len(sorted_idx) == 1:
    return [[sorted_idx[0]]]

  gaps = np.diff(sorted_idx)
  split_points = np.where(gaps > max_gap)[0] + 1
  clusters = np.split(sorted_idx, split_points)
  clusters = [c.tolist() for c in clusters]

  # Periksa penyambungan wrap-around antara ujung akhir dan awal
  wrap_gap = (360 - sorted_idx[-1]) + sorted_idx[0]
  if wrap_gap <= max_gap and len(clusters) > 1:
    clusters[0] = clusters[-1] + clusters[0]
    clusters.pop()

  return clusters


# =====================================================================
# 3. DETEKSI FITUR UI, TARGET PUTIH, & JARUM MERAH
# =====================================================================
def is_skillcheck_ui_present(frame):
  """Mendeteksi keberadaan UI Skill Check Violence District secara akurat.

  Di pusat lingkaran terdapat ikon tombol spasi [_] dengan container gelap. Fitur
  ini mencegah salah deteksi pada baju karakter, topi, aksesoris, atau world 3D.
  """
  # Kotak ikon spasi di tengah lingkaran (cx, cy)
  box = frame[cy - 15 : cy + 15, cx - 20 : cx + 20]
  # Background kotak harus gelap (RGB < 55)
  dark_mask = (box[:, :, 0] < 55) & (box[:, :, 1] < 55) & (box[:, :, 2] < 55)
  dark_ratio = np.mean(dark_mask)

  # Ikon tombol spasi putih di tengah kotak (RGB > 170)
  white_mask = (
      (box[:, :, 0] > 170) & (box[:, :, 1] > 170) & (box[:, :, 2] > 170)
  )
  white_count = np.sum(white_mask)

  return (dark_ratio >= 0.45) and (70 <= white_count <= 350)


def detect_white_target(frame):
  """Mendeteksi balok putih tebal (Great/Perfect Zone).

  Harus memiliki ketebalan radial (>= 2 lapisan) dan lebar sudut 2° - 16°.
  """
  target_votes = np.zeros(360, dtype=np.int16)
  for rx, ry in target_coords:
    p = frame[ry, rx]
    B = p[:, 0].astype(int)
    G = p[:, 1].astype(int)
    R = p[:, 2].astype(int)
    is_white = (
        (R > 195)
        & (G > 195)
        & (B > 195)
        & (np.abs(R - G) < 30)
        & (np.abs(R - B) < 30)
    )
    target_votes += is_white.astype(np.int16)

  candidates = np.where(target_votes >= 2)[0]
  if len(candidates) == 0:
    return None, 0.0

  clusters = find_circular_clusters(candidates, max_gap=2)
  valid_clusters = [c for c in clusters if 2 <= len(c) <= 16]
  if not valid_clusters:
    return None, 0.0

  # Ambil cluster yang paling padat
  best_cluster = max(valid_clusters, key=len)
  target_angle = circular_mean_angle(best_cluster)
  target_width = float(len(best_cluster))
  return target_angle, target_width


def detect_red_needle(frame, prev_angle=None):
  """Mendeteksi jarum merah dengan multi-radial voting across 5 concentric rings.

  Menolak pixel noise dan background statis.
  """
  needle_votes = np.zeros(360, dtype=np.int16)
  for rx, ry in needle_coords:
    p = frame[ry, rx]
    B = p[:, 0].astype(int)
    G = p[:, 1].astype(int)
    R = p[:, 2].astype(int)
    is_red = (
        (R > 115)
        & (R - G > 35)
        & (R - B > 35)
        & (R > G * 1.30)
        & (R > B * 1.30)
    )
    needle_votes += is_red.astype(np.int16)

  candidates = np.where(needle_votes >= 2)[0]
  if len(candidates) == 0:
    # Coba toleransi 1 vote jika sedang aktif tracking
    if prev_angle is not None:
      candidates = np.where(needle_votes >= 1)[0]
    if len(candidates) == 0:
      return None, 0.0

  clusters = find_circular_clusters(candidates, max_gap=2)
  valid_clusters = [c for c in clusters if 1 <= len(c) <= 12]
  if not valid_clusters:
    return None, 0.0

  if prev_angle is not None and len(valid_clusters) > 1:

    def dist_from_prev(c):
      m = circular_mean_angle(c)
      return (m - prev_angle) % 360

    forward_clusters = [c for c in valid_clusters if 0 <= dist_from_prev(c) <= 40]
    if forward_clusters:
      best_cluster = min(forward_clusters, key=dist_from_prev)
    else:
      best_cluster = max(valid_clusters, key=len)
  else:
    best_cluster = max(valid_clusters, key=len)

  needle_angle = circular_mean_angle(best_cluster)
  needle_width = float(len(best_cluster))
  return needle_angle, needle_width


# =====================================================================
# 4. GUI & DEBUG CAPTURE VISUALIZER
# =====================================================================
gui_queue = queue.Queue()
gui_stop_event = threading.Event()
latest_capture_dir = None


def gui_worker_loop():
  """Thread terpisah khusus OpenCV GUI agar main loop tidak mengalami latency."""
  window_name = (
      "VD Skill Check - Space Hit Debug Viewer (Tekan 'Q' di window ini untuk"
      " tutup)"
  )
  cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
  cv2.resizeWindow(window_name, 1100, 240)

  welcome = np.zeros((240, 1100, 3), dtype=np.uint8)
  welcome[:] = (25, 25, 25)
  cv2.putText(
      welcome,
      "VD Skill Check Bot - Siap Menunggu Event Hit...",
      (30, 100),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.8,
      (0, 255, 200),
      2,
  )
  cv2.putText(
      welcome,
      "Saat bot menekan Space, seluruh sequence capture pre-hit & post-hit akan"
      " tampil disini.",
      (30, 150),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.55,
      (180, 180, 180),
      1,
  )
  cv2.imshow(window_name, welcome)

  while not gui_stop_event.is_set():
    try:
      img = gui_queue.get(timeout=0.04)
      cv2.imshow(window_name, img)
    except queue.Empty:
      pass
    key = cv2.waitKey(20) & 0xFF
    if key == ord("q"):
      pass

  cv2.destroyAllWindows()


def annotate_frame(
    raw_frame,
    label,
    needle_angle=None,
    target_angle=None,
    dist=None,
    is_hit=False,
):
  """Menambahkan overlay garis visual jarum, target, dan keterangan teks."""
  canvas = raw_frame[:, :, :3].copy()

  # Gambar lingkaran track
  cv2.circle(canvas, (cx, cy), R_MID, (70, 70, 70), 2)

  # Gambar target zone jika ada
  if target_angle is not None:
    rad_t = np.deg2rad(target_angle)
    tx = int(round(cx + R_MID * np.cos(rad_t)))
    ty = int(round(cy + R_MID * np.sin(rad_t)))
    cv2.circle(canvas, (tx, ty), 6, (0, 255, 0), -1)
    cv2.circle(canvas, (tx, ty), 7, (255, 255, 255), 1)

  # Gambar jarum merah jika ada
  if needle_angle is not None:
    rad_n = np.deg2rad(needle_angle)
    nx = int(round(cx + (R_MID - 2) * np.cos(rad_n)))
    ny = int(round(cy + (R_MID - 2) * np.sin(rad_n)))
    needle_color = (0, 255, 255) if is_hit else (0, 0, 255)
    cv2.line(canvas, (cx, cy), (nx, ny), needle_color, 2)
    cv2.circle(canvas, (nx, ny), 3, (255, 255, 255), -1)

  # Label strip di bagian atas
  header_bg = (0, 140, 0) if is_hit else (40, 40, 40)
  cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 24), header_bg, -1)
  cv2.putText(
      canvas,
      label,
      (4, 17),
      cv2.FONT_HERSHEY_SIMPLEX,
      0.42,
      (255, 255, 255),
      1,
      cv2.LINE_AA,
  )

  # Label info di bagian bawah
  info_str = ""
  if needle_angle is not None:
    info_str += f"N:{needle_angle:.1f}"
  if target_angle is not None:
    info_str += f" T:{target_angle:.1f}"
  if dist is not None:
    info_str += f" D:{dist:.1f}"

  if info_str:
    cv2.rectangle(
        canvas,
        (0, canvas.shape[0] - 20),
        (canvas.shape[1], canvas.shape[0]),
        (20, 20, 20),
        -1,
    )
    cv2.putText(
        canvas,
        info_str,
        (4, canvas.shape[0] - 5),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (0, 255, 255),
        1,
        cv2.LINE_AA,
    )

  return canvas


def build_and_save_debug_package(
    pre_records, hit_record, post_records, summary_stats
):
  """Menyimpan seluruh frame sequence dan membuat image montage gabungan."""
  global latest_capture_dir
  now_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
  folder_path = os.path.join(os.getcwd(), "debug_captures", f"hit_{now_str}")
  os.makedirs(folder_path, exist_ok=True)
  latest_capture_dir = folder_path

  annotated_frames = []
  all_records = []

  for i, rec in enumerate(pre_records):
    offset_ms = int((rec["time"] - hit_record["time"]) * 1000)
    label = f"PRE-{len(pre_records)-i} ({offset_ms}ms)"
    all_records.append((rec, label, False))

  all_records.append((hit_record, ">>> HIT (SPACE) <<<", True))

  for i, rec in enumerate(post_records):
    offset_ms = int((rec["time"] - hit_record["time"]) * 1000)
    label = f"POST+{i+1} (+{offset_ms}ms)"
    all_records.append((rec, label, False))

  for idx, (rec, label, is_hit) in enumerate(all_records):
    ann = annotate_frame(
        rec["img"],
        label,
        needle_angle=rec.get("needle_angle"),
        target_angle=rec.get("target_angle"),
        dist=rec.get("dist"),
        is_hit=is_hit,
    )
    annotated_frames.append(ann)
    filename = f"{idx+1:02d}_{'HIT_SPACE' if is_hit else 'frame'}.png"
    cv2.imwrite(os.path.join(folder_path, filename), ann)

  # Susun Montage Horizontal
  montage_row = np.hstack(annotated_frames)
  banner_h = 48
  banner = np.zeros((banner_h, montage_row.shape[1], 3), dtype=np.uint8)
  banner[:] = (25, 25, 25)

  err = summary_stats.get("offset_deg", 0.0)
  target_val = summary_stats.get("target_deg", 0.0)
  needle_val = summary_stats.get("needle_deg", 0.0)
  speed_val = summary_stats.get("speed_deg_s", 0.0)
  eval_str = (
      "PERFECT HIT (SEMPURNA!)"
      if abs(err) <= 3.5
      else ("GOOD HIT" if abs(err) <= 6.5 else "MISS/LATE")
  )
  banner_color = (
      (0, 255, 0)
      if "PERFECT" in eval_str
      else ((0, 255, 255) if "GOOD" in eval_str else (0, 0, 255))
  )

  title_line = (
      f"HIT #{summary_stats.get('hit_count', 1)} |"
      f" {summary_stats.get('timestamp', '')} | {eval_str}"
  )
  sub_line = (
      f"Target: {target_val:.1f} deg | Jarum: {needle_val:.1f} deg | Offset:"
      f" {err:+.2f} deg | Kecepatan: {speed_val:.1f} deg/s"
  )

  font_scale = 0.45 if montage_row.shape[1] < 700 else 0.52

  cv2.putText(
      banner,
      title_line,
      (8, 20),
      cv2.FONT_HERSHEY_SIMPLEX,
      font_scale,
      banner_color,
      1,
      cv2.LINE_AA,
  )
  cv2.putText(
      banner,
      sub_line,
      (8, 40),
      cv2.FONT_HERSHEY_SIMPLEX,
      font_scale - 0.05,
      (220, 220, 220),
      1,
      cv2.LINE_AA,
  )

  final_montage = np.vstack([banner, montage_row])
  montage_path = os.path.join(folder_path, "summary_montage.png")
  cv2.imwrite(montage_path, final_montage)

  gui_queue.put(final_montage)

  return folder_path, montage_path, eval_str


# =====================================================================
# 5. HOTKEY & KONTROL
# =====================================================================
bot_active = True
request_calib = False
request_exit = False


def toggle_pause():
  global bot_active
  bot_active = not bot_active
  print(f"\n[STATUS] Bot: {'>>> AKTIF <<<' if bot_active else '|| PAUSED ||'}")


def trigger_calib():
  global request_calib
  request_calib = True


def trigger_exit():
  global request_exit
  request_exit = True


def open_capture_folder():
  global latest_capture_dir
  if latest_capture_dir and os.path.exists(latest_capture_dir):
    try:
      os.startfile(latest_capture_dir)
      print(f"[INFO] Membuka folder debug capture: {latest_capture_dir}")
    except Exception as e:
      print(f"[ERROR] Gagal membuka folder: {e}")
  else:
    print("[INFO] Belum ada capture debug yang tersimpan.")


def start_gui_thread():
  gui_thread = threading.Thread(target=gui_worker_loop, daemon=True)
  gui_thread.start()
  return gui_thread


# =====================================================================
# 6. MAIN LOOP
# =====================================================================
def main():
  global bot_active, request_calib, request_exit, latest_capture_dir
  start_gui_thread()

  keyboard.add_hotkey("insert", toggle_pause)
  keyboard.add_hotkey("x", trigger_calib)
  keyboard.add_hotkey("o", open_capture_folder)
  keyboard.add_hotkey("end", trigger_exit)

  print("==========================================================")
  print("   BOT SKILL CHECK VD (ANTI-FAIL & SMART AUTO DETECT)   ")
  print("==========================================================")
  print(" Hotkeys:")
  print("  - [INSERT] : Pause / Resume Bot")
  print("  - [X]      : Simpan gambar kalibrasi 'cek_kalibrasi.png'")
  print("  - [O]      : Buka folder capture screenshot terakhir di Explorer")
  print("  - [END]    : Keluar dari program")
  print("----------------------------------------------------------")
  print(" Peningkatan Versi Ini:")
  print("  1. Center UI Validator: 100% Anti-False Click pada baju/topi/background.")
  print("  2. Anti-Cooldown Freeze: Bebas dari bug macet yang membuat generator meledak.")
  print("  3. Fail-Safe Hit Trigger: Menjamin klik bahkan saat terjadi frame stutter.")
  print("==========================================================\n")

  STATE_IDLE = "IDLE"
  STATE_TRACKING = "TRACKING"
  STATE_COOLDOWN = "COOLDOWN"

  current_state = STATE_IDLE
  locked_target_angle = None
  locked_target_width = 6.0
  target_samples = []

  needle_prev_angle = None
  needle_prev_time = None
  needle_speed = 300.0
  needle_confirm_count = 0
  last_ui_seen_time = 0.0
  cooldown_until = 0.0
  hit_counter = 0

  frame_buffer = collections.deque(maxlen=10)

  with mss.mss() as sct:
    print("[READY] Bot aktif & siap memantau skill check (150+ FPS)...\n")

    while not request_exit:
      loop_start_time = time.perf_counter()

      if not bot_active:
        time.sleep(0.03)
        continue

      # 1. Grab Frame dari Monitor ROI
      frame = np.array(sct.grab(monitor_roi))
      now = time.perf_counter()

      # Fitur Kalibrasi Snapshot [X]
      if request_calib:
        preview = frame[:, :, :3].copy()
        for x, y in zip(in_x, in_y):
          preview[y, x] = [255, 255, 0]  # Cyan
        for x, y in zip(mid_x, mid_y):
          preview[y, x] = [0, 255, 0]  # Green
        for x, y in zip(out_x, out_y):
          preview[y, x] = [0, 165, 255]  # Orange
        cv2.drawMarker(
            preview,
            (cx, cy),
            (0, 0, 255),
            markerType=cv2.MARKER_CROSS,
            markerSize=10,
            thickness=1,
        )
        cv2.imwrite("cek_kalibrasi.png", preview)
        print(f"[INFO] Kalibrasi disimpan ke 'cek_kalibrasi.png' pada {now:.2f}")
        request_calib = False

      # 2. State: COOLDOWN (Fix bug macet: cooldown punya hard timeout & cek UI center)
      if current_state == STATE_COOLDOWN:
        if now < cooldown_until:
          time.sleep(0.005)
          continue
        else:
          # Cek apakah UI skill check sudah benar-benar hilang dari layar
          ui_still_active = is_skillcheck_ui_present(frame)
          # Hard timeout 0.4s setelah cooldown_until agar tidak pernah macet
          if not ui_still_active or now > (cooldown_until + 0.35):
            current_state = STATE_IDLE
            locked_target_angle = None
            target_samples.clear()
            needle_prev_angle = None
            needle_prev_time = None
            needle_confirm_count = 0
            frame_buffer.clear()
            print("[IDLE] Skill check selesai. Siap menunggu berikutnya...")
          continue

      # 3. Validasi UI Skill Check (Anti-Ghost Click pada Baju/Topi/Darah)
      ui_present = is_skillcheck_ui_present(frame)

      if not ui_present:
        if current_state == STATE_TRACKING:
          # Jika UI menghilang tiba-tiba selama > 0.15s, reset ke IDLE
          if (now - last_ui_seen_time) > 0.15:
            current_state = STATE_IDLE
            locked_target_angle = None
            target_samples.clear()
            needle_prev_angle = None
            needle_prev_time = None
            needle_confirm_count = 0
            frame_buffer.clear()
        time.sleep(0.002)
        continue

      # Jika UI Skill Check aktif di layar:
      last_ui_seen_time = now

      # 4. Deteksi Target Putih & Jarum Merah
      detected_target, target_w = detect_white_target(frame)
      detected_needle, needle_w = detect_red_needle(
          frame, prev_angle=needle_prev_angle
      )

      # 5. Kunci & Perhalus Sudut Target Putih
      if detected_target is not None:
        if locked_target_angle is None:
          target_samples = [detected_target]
          locked_target_angle = detected_target
          locked_target_width = max(4.0, target_w)
          current_state = STATE_TRACKING
          print(
              f"[TARGET] Balok putih terdeteksi di: {locked_target_angle:.1f}°"
              f" (Lebar: {locked_target_width:.1f}°)"
          )
        else:
          signed_dist = (
              get_signed_angle_diff(detected_needle, locked_target_angle)
              if detected_needle is not None
              else -100.0
          )
          # Perhalus estimasi target di beberapa frame awal saat jarum masih jauh
          if signed_dist < -25.0 and len(target_samples) < 5:
            target_samples.append(detected_target)
            locked_target_angle = circular_mean_angle(target_samples)

      # 6. Pelacakan Jarum & Kecepatan
      cw_dist = None
      if detected_needle is not None:
        if needle_prev_angle is not None and needle_prev_time is not None:
          dt = now - needle_prev_time
          if dt > 0:
            d_theta = (detected_needle - needle_prev_angle) % 360
            if 0.2 <= d_theta <= 40.0:
              inst_speed = d_theta / dt
              if 120.0 <= inst_speed <= 650.0:
                needle_confirm_count += 1
                needle_speed = 0.65 * needle_speed + 0.35 * inst_speed
            elif d_theta < 0.2:
              needle_confirm_count = max(0, needle_confirm_count - 1)

        needle_prev_angle = detected_needle
        needle_prev_time = now

        if locked_target_angle is not None:
          cw_dist = clockwise_distance(locked_target_angle, detected_needle)

      # Simpan frame ke rolling buffer untuk debug visualizer
      frame_buffer.append({
          "img": frame,
          "time": now,
          "needle_angle": detected_needle,
          "target_angle": locked_target_angle,
          "dist": cw_dist,
          "speed": needle_speed,
      })

      # 7. Evaluasi Trigger Eksekusi Spasi (Predictive Lead + Stutter Fail-Safe)
      if locked_target_angle is not None and detected_needle is not None:
        signed_err = get_signed_angle_diff(
            detected_needle, locked_target_angle
        )
        should_press = False
        remaining_delay = 0.0

        # Kasus A: Jarum sedang mendekati target dalam jarak 35 derajat
        if -35.0 <= signed_err < 0.0:
          dist_remaining = -signed_err
          time_to_hit = dist_remaining / max(150.0, needle_speed)

          if time_to_hit <= (HARDWARE_LATENCY_SEC + 0.010):
            should_press = True
            remaining_delay = max(0.0, time_to_hit - HARDWARE_LATENCY_SEC)

        # Kasus B (Fail-Safe Stutter): Jarum sudah berada di dalam balok putih (center s/d trailing edge)
        elif 0.0 <= signed_err <= (locked_target_width / 2.0 + 1.5):
          # Jika frame rate sempat drop dan jarum melompat masuk ke balok putih, langsung klik!
          should_press = True
          remaining_delay = 0.0

        if should_press:
          hit_counter += 1
          hit_moment_time = now
          hit_needle_angle = detected_needle
          hit_target_angle = locked_target_angle

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
              "speed": needle_speed,
          }

          post_records = []
          for _ in range(2):
            time.sleep(0.025)
            p_frame = np.array(sct.grab(monitor_roi))
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
              list(frame_buffer)[-5:-1]
              if len(frame_buffer) >= 5
              else list(frame_buffer)[:-1]
          )

          expected_hit_angle = (
              hit_needle_angle + needle_speed * HARDWARE_LATENCY_SEC
          ) % 360
          offset = (expected_hit_angle - hit_target_angle + 180) % 360 - 180

          stats = {
              "hit_count": hit_counter,
              "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:12],
              "target_deg": hit_target_angle,
              "needle_deg": hit_needle_angle,
              "offset_deg": offset,
              "speed_deg_s": needle_speed,
          }

          saved_dir, montage_file, eval_str = build_and_save_debug_package(
              pre_records, hit_record, post_records, stats
          )

          print(
              f"\n[TRIGGER HIT #{hit_counter}] >>> SPACE DITEKAN! <<<"
              f" [{eval_str}]"
          )
          print(
              f"  | Target: {hit_target_angle:.1f}° | Jarum saat klik:"
              f" {hit_needle_angle:.1f}°"
          )
          print(
              f"  | Kecepatan Jarum: {needle_speed:.1f}°/s | Estimasi Offset:"
              f" {offset:+.2f}°"
          )
          print(f"  | Capture Disimpan: {saved_dir}")
          print(
              "  | [INFO] Preview visual capture telah ditampilkan di jendela"
              " GUI!\n"
          )

          # Cooldown terkontrol (tepat 0.5 detik, tanpa loop tak terhingga)
          current_state = STATE_COOLDOWN
          cooldown_until = time.perf_counter() + 0.50
          continue

      elapsed = time.perf_counter() - loop_start_time
      if elapsed < 0.003:
        time.sleep(0.001)

  gui_stop_event.set()
  print("[INFO] Program selesai. Sampai jumpa!")


if __name__ == "__main__":
  main()