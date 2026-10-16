"""Utilitas matematika sirkular dan algoritma clustering sudut 360 derajat."""

from typing import List, Union
import numpy as np


def circular_mean_angle(deg_array: Union[List[float], np.ndarray]) -> float:
  """Menghitung sudut rata-rata sirkular dalam derajat [0, 360)."""
  rads = np.deg2rad(deg_array)
  mean_rad = np.arctan2(np.mean(np.sin(rads)), np.mean(np.cos(rads)))
  return float(np.rad2deg(mean_rad) % 360)


def clockwise_distance(target: float, current: float) -> float:
  """Jarak tempuh searah jarum jam (clockwise) dari current menuju target."""
  return float((target - current) % 360)


def get_signed_angle_diff(needle: float, target: float) -> float:
  """Selisih sudut bertanda dari target ke needle dalam rentang [-180, 180].

  Negatif: jarum berada sebelum target (sedang mendekati).
  Positif: jarum sudah melewati target.
  """
  return float((needle - target + 180) % 360 - 180)


def find_circular_clusters(
    active_indices: Union[List[int], np.ndarray], max_gap: int = 2
) -> List[List[int]]:
  """Mengelompokkan indeks sudut yang berdekatan menjadi cluster contiguous,

  dengan menangani wrap-around pada titik 359 -> 0 derajat.
  """
  if len(active_indices) == 0:
    return []
  sorted_idx = np.sort(np.unique(active_indices))
  if len(sorted_idx) == 1:
    return [[int(sorted_idx[0])]]

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
