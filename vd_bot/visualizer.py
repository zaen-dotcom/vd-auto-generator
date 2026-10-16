"""Modul visualisasi GUI live dan penyimpanan paket debug capture saat event hit."""

from datetime import datetime
import os
import queue
import threading
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from vd_bot.config import CX, CY, R_MID

gui_queue = queue.Queue()
gui_stop_event = threading.Event()
latest_capture_dir: Optional[str] = None


def gui_worker_loop():
  """Thread terpisah khusus OpenCV GUI agar main tracking loop tidak mengalami latency."""
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


def start_gui_thread() -> threading.Thread:
  """Memulai background thread untuk GUI visualizer OpenCV."""
  gui_stop_event.clear()
  gui_thread = threading.Thread(target=gui_worker_loop, daemon=True)
  gui_thread.start()
  return gui_thread


def stop_gui_thread():
  """Menghentikan thread GUI visualizer."""
  gui_stop_event.set()


def open_capture_folder():
  """Membuka folder capture debug screenshot terakhir di Windows Explorer."""
  global latest_capture_dir
  if latest_capture_dir and os.path.exists(latest_capture_dir):
    try:
      os.startfile(latest_capture_dir)
      print(f"[INFO] Membuka folder debug capture: {latest_capture_dir}")
    except Exception as e:
      print(f"[ERROR] Gagal membuka folder: {e}")
  else:
    print("[INFO] Belum ada capture debug yang tersimpan.")


def annotate_frame(
    raw_frame: np.ndarray,
    label: str,
    needle_angle: Optional[float] = None,
    target_angle: Optional[float] = None,
    dist: Optional[float] = None,
    is_hit: bool = False,
) -> np.ndarray:
  """Menambahkan overlay garis visual jarum, target, dan keterangan teks."""
  canvas = raw_frame[:, :, :3].copy()

  # Gambar lingkaran track
  cv2.circle(canvas, (CX, CY), R_MID, (70, 70, 70), 2)

  # Gambar target zone jika ada
  if target_angle is not None:
    rad_t = np.deg2rad(target_angle)
    tx = int(round(CX + R_MID * np.cos(rad_t)))
    ty = int(round(CY + R_MID * np.sin(rad_t)))
    cv2.circle(canvas, (tx, ty), 6, (0, 255, 0), -1)
    cv2.circle(canvas, (tx, ty), 7, (255, 255, 255), 1)

  # Gambar jarum merah jika ada
  if needle_angle is not None:
    rad_n = np.deg2rad(needle_angle)
    nx = int(round(CX + (R_MID - 2) * np.cos(rad_n)))
    ny = int(round(CY + (R_MID - 2) * np.sin(rad_n)))
    needle_color = (0, 255, 255) if is_hit else (0, 0, 255)
    cv2.line(canvas, (CX, CY), (nx, ny), needle_color, 2)
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
    pre_records: List[Dict[str, Any]],
    hit_record: Dict[str, Any],
    post_records: List[Dict[str, Any]],
    summary_stats: Dict[str, Any],
) -> Tuple[str, str, str]:
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
