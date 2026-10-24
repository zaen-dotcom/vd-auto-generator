"""Modul computer vision untuk mendeteksi UI Skill Check, Balok Putih (Great/Perfect Zone),

dan Jarum Merah (Needle).
"""

from typing import Optional, Tuple
import numpy as np

from vd_bot.config import (
    CONTRAST_IN_X,
    CONTRAST_IN_Y,
    CONTRAST_OUT_X,
    CONTRAST_OUT_Y,
    CX,
    CY,
    GOOD_ZONE_COORDS,
    MID_X,
    MID_Y,
    NEEDLE_COORDS,
    R_MID,
    TARGET_COORDS,
)
from vd_bot.math_utils import circular_mean_angle, find_circular_clusters


# Buffer pre-allocated untuk eliminasi alokasi memori berulang di loop (Zero Heap Churn)
_target_votes_buf = np.zeros(360, dtype=np.int16)
_dark_votes_buf = np.zeros(360, dtype=np.int16)
_needle_votes_buf = np.zeros(360, dtype=np.int16)


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

  # Ikon tombol spasi putih di tengah kotak (RGB > 150)
  white_mask = (
      (box[:, :, 0] > 150) & (box[:, :, 1] > 150) & (box[:, :, 2] > 150)
  )
  white_count = np.sum(white_mask)

  return bool((dark_ratio >= 0.45) and (30 <= white_count <= 350))


def detect_white_target(
    frame: np.ndarray,
) -> Tuple[Optional[float], float, str]:
  """Mendeteksi target hit skillcheck dengan filter cerdas anti-baju/tembok putih.

  Prioritas 1: Balok Putih (Perfect Zone)
    - Multi-radial voting across 5 concentric rings.
    - Filter Kontras Radial: Balok UI memiliki batas kontras tajam terhadap
      background dalam (R_MID - 8) dan luar (R_MID + 8). Baju/tembok putih
      otomatis ditolak karena tidak memiliki kontras radial tajam.
    - Anchor Kontekstual: Balok putih selalu menempel di ujung area hitam (Good Zone).

  Prioritas 2: Area Hitam (Good Zone Fallback)
    - Jika balok putih belum/tidak terdeteksi, deteksi busur hitam Good Zone
      sebagai target cadangan agar tetap berhasil Good Hit tanpa gagal skill check.

  Returns:
    (target_angle, target_width, target_type)
    target_type: 'PERFECT_WHITE', 'GOOD_BLACK', atau 'NONE'
  """
  _target_votes_buf.fill(0)
  target_votes = _target_votes_buf

  # 1. Voting multi-ring untuk piksel putih
  for rx, ry in TARGET_COORDS:
    p = frame[ry, rx]
    B = p[:, 0].astype(int)
    G = p[:, 1].astype(int)
    R = p[:, 2].astype(int)
    is_white = (
        (R > 190)
        & (G > 190)
        & (B > 190)
        & (np.abs(R - G) < 25)
        & (np.abs(R - B) < 25)
    )
    target_votes += is_white.astype(np.int16)

  candidates = np.where(target_votes >= 2)[0]
  if len(candidates) > 0:
    clusters = find_circular_clusters(candidates, max_gap=2)
    valid_clusters = [c for c in clusters if 2 <= len(c) <= 16]

    scored_white = []
    for c in valid_clusters:
      mean_ang = circular_mean_angle(c)
      idx = int(round(mean_ang)) % 360

      # Verifikasi Kontras Radial terhadap background dalam & luar
      p_mid = frame[MID_Y[idx], MID_X[idx]]
      p_in = frame[CONTRAST_IN_Y[idx], CONTRAST_IN_X[idx]]
      p_out = frame[CONTRAST_OUT_Y[idx], CONTRAST_OUT_X[idx]]

      br_mid = (int(p_mid[0]) + int(p_mid[1]) + int(p_mid[2])) // 3
      br_in = (int(p_in[0]) + int(p_in[1]) + int(p_in[2])) // 3
      br_out = (int(p_out[0]) + int(p_out[1]) + int(p_out[2])) // 3

      radial_contrast = (br_mid - br_in) + (br_mid - br_out)

      # Eliminasi baju putih / tembok putih yang tidak memiliki kontras radial tajam
      if radial_contrast < 50:
        continue

      # Verifikasi keberadaan area hitam di belakang balok putih (arah berlawanan jarum jam)
      dark_samples = 0
      for off in (4, 8, 12, 16, 20, 24):
        test_idx = (idx - off) % 360
        tp = frame[MID_Y[test_idx], MID_X[test_idx]]
        if tp[0] < 55 and tp[1] < 55 and tp[2] < 55:
          dark_samples += 1

      score = radial_contrast + (dark_samples * 20) + (len(c) * 10)
      scored_white.append((score, mean_ang, float(len(c))))

    if scored_white:
      scored_white.sort(key=lambda x: x[0], reverse=True)
      best = scored_white[0]
      return best[1], best[2], 'PERFECT_WHITE'

  # 2. Prioritas 2: Area Hitam (Good Zone Fallback)
  _dark_votes_buf.fill(0)
  dark_votes = _dark_votes_buf
  for rx, ry in GOOD_ZONE_COORDS:
    p = frame[ry, rx]
    is_dark = (p[:, 0] < 55) & (p[:, 1] < 55) & (p[:, 2] < 55)
    dark_votes += is_dark.astype(np.int16)

  dark_candidates = np.where(dark_votes >= 2)[0]
  if len(dark_candidates) > 0:
    dark_clusters = find_circular_clusters(dark_candidates, max_gap=3)
    good_zones = [c for c in dark_clusters if 15 <= len(c) <= 65]
    if good_zones:
      best_gz = max(good_zones, key=len)
      # Titik kontak ideal berada di bagian ujung akhir busur (80% panjang busur)
      hit_ang = (best_gz[0] + len(best_gz) * 0.8) % 360
      return hit_ang, float(len(best_gz)), 'GOOD_BLACK'

  return None, 0.0, 'NONE'


def detect_red_needle(
    frame: np.ndarray, prev_angle: Optional[float] = None
) -> Tuple[Optional[float], float]:
  """Mendeteksi jarum merah dengan multi-radial voting across 5 concentric rings.

  Menolak pixel noise dan background statis.
  """
  _needle_votes_buf.fill(0)
  needle_votes = _needle_votes_buf
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
