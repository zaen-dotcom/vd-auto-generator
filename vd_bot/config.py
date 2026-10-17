"""Konfigurasi kalibrasi posisi, radius, timing, dan lookup table koordinat."""

import numpy as np

# =====================================================================
# 1. KONFIGURASI KALIBRASI & TIMING
# =====================================================================
CENTER_X = 959
CENTER_Y = 566
R_MID = 66
R_IN = R_MID - 3  # 63 px
R_OUT = R_MID + 3  # 69 px

# Estimasi latency hardware + input buffer (dalam detik)
# Rata-rata SendInput + game frame rendering delay adalah 15-18ms
HARDWARE_LATENCY_SEC = 0.016

PADDING = 20
HALF_BOX = R_OUT + PADDING  # 89 px

MONITOR_ROI = {
    "top": CENTER_Y - HALF_BOX,
    "left": CENTER_X - HALF_BOX,
    "width": HALF_BOX * 2,
    "height": HALF_BOX * 2,
}

ANGLES_DEG = np.arange(360)
ANGLES_RAD = np.deg2rad(ANGLES_DEG)
CX, CY = HALF_BOX, HALF_BOX


def create_ring_coords(radius: int):
  """Menghasilkan koordinat piksel (rx, ry) sepanjang 360 derajat untuk radius tertentu."""
  rx = np.round(CX + radius * np.cos(ANGLES_RAD)).astype(int)
  ry = np.round(CY + radius * np.sin(ANGLES_RAD)).astype(int)
  return rx, ry


# Radius sensor untuk balok putih (Perfect Target Zone)
TARGET_RADII = [R_MID - 2, R_MID - 1, R_MID, R_MID + 1, R_MID + 2]
TARGET_COORDS = [create_ring_coords(r) for r in TARGET_RADII]

# Radius sensor untuk jarum merah (Needle Tracking)
NEEDLE_RADII = [R_MID - 6, R_MID - 11, R_MID - 16, R_MID - 21, R_MID - 26]
NEEDLE_COORDS = [create_ring_coords(r) for r in NEEDLE_RADII]

# Cincin preview kalibrasi
IN_X, IN_Y = create_ring_coords(R_IN)
MID_X, MID_Y = create_ring_coords(R_MID)
OUT_X, OUT_Y = create_ring_coords(R_OUT)

# =====================================================================
# 2. FITUR DEBUG & CAPTURES
# =====================================================================
# Set True jika ingin merekam frame dan membuka jendela GUI visualizer saat hit
# Set False untuk mematikan capture foto agar disk tidak penuh & performa maksimal
ENABLE_DEBUG_CAPTURES = True

# =====================================================================
# 3. FITUR CROSSHAIR PISTOL (TITIK HIJAU OVERLAY)
# =====================================================================
# Set True untuk menampilkan titik hijau kecil di tengah layar untuk mempermudah bidikan pistol
ENABLE_CROSSHAIR = True
# Titik tengah aim tembakan pistol (default: tengah monitor 1920x1080 = 960, 540)
CROSSHAIR_X = 960
CROSSHAIR_Y = 540
# Ukuran radius titik hijau (2 = titik kecil tajam/presisi, 3 = sedikit lebih tebal)
CROSSHAIR_RADIUS = 2
# Warna titik (Hex): hijau neon terang dengan outline hitam
CROSSHAIR_COLOR = "#00FF66"
