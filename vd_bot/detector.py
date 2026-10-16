"""Modul computer vision untuk mendeteksi UI Skill Check, Balok Putih (Great/Perfect Zone),

dan Jarum Merah (Needle).
"""

from typing import Optional, Tuple
import numpy as np

from vd_bot.config import CX, CY, NEEDLE_COORDS, TARGET_COORDS
from vd_bot.math_utils import circular_mean_angle, find_circular_clusters


def is_skillcheck_ui_present(frame: np.ndarray) -> bool:
  """Mendeteksi keberadaan UI Skill Check Violence District secara akurat.

  Di pusat lingkaran terdapat ikon tombol spasi [_] dengan container gelap. Fitur
  ini mencegah salah deteksi pada baju karakter, topi, aksesoris, atau world 3D.
  """
  # Kotak ikon spasi di tengah lingkaran (CX, CY)
  box = frame[CY - 15 : CY + 15, CX - 20 : CX + 20]
  # Background kotak harus gelap (RGB < 55)
  dark_mask = (box[:, :, 0] < 55) & (box[:, :, 1] < 55) & (box[:, :, 2] < 55)
  dark_ratio = np.mean(dark_mask)

  # Ikon tombol spasi putih di tengah kotak (RGB > 170)
  white_mask = (
      (box[:, :, 0] > 170) & (box[:, :, 1] > 170) & (box[:, :, 2] > 170)
  )
  white_count = np.sum(white_mask)

  return bool((dark_ratio >= 0.45) and (70 <= white_count <= 350))


def detect_white_target(frame: np.ndarray) -> Tuple[Optional[float], float]:
  """Mendeteksi balok putih tebal (Great/Perfect Zone).

  Harus memiliki ketebalan radial (>= 2 lapisan) dan lebar sudut 2° - 16°.
  """
  target_votes = np.zeros(360, dtype=np.int16)
  for rx, ry in TARGET_COORDS:
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


def detect_red_needle(
    frame: np.ndarray, prev_angle: Optional[float] = None
) -> Tuple[Optional[float], float]:
  """Mendeteksi jarum merah dengan multi-radial voting across 5 concentric rings.

  Menolak pixel noise dan background statis.
  """
  needle_votes = np.zeros(360, dtype=np.int16)
  for rx, ry in NEEDLE_COORDS:
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
    # Toleransi 1 vote jika sedang aktif tracking
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
