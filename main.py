"""Entry point utama untuk menjalankan VD Auto Generator (Violence District Bot)."""

import sys
from vd_bot import BotEngine


def main():
  bot = BotEngine()
  try:
    bot.start()
  except KeyboardInterrupt:
    print("\n[INFO] Bot dihentikan oleh pengguna.")
    sys.exit(0)


if __name__ == "__main__":
  main()
