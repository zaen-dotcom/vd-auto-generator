"""Backward-compatible entry point untuk menjalankan VD Auto Generator.

Dapat dijalankan langsung melalui 'python vd_perfect_bot.py' atau 'start.bat'.
Menggunakan modul baru yang telah dipecah secara profesional pada package 'vd_bot'.
"""

from main import main
from vd_bot.config import *
from vd_bot.detector import *
from vd_bot.engine import BotEngine
from vd_bot.input_controller import *
from vd_bot.math_utils import *
from vd_bot.visualizer import *

if __name__ == "__main__":
  main()