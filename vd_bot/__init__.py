"""VD Auto Generator - Violence District Skill Check Automation Package."""

from vd_bot.config import (
    CENTER_X,
    CENTER_Y,
    HARDWARE_LATENCY_SEC,
    MONITOR_ROI,
    R_IN,
    R_MID,
    R_OUT,
)
from vd_bot.crosshair import CrosshairOverlay
from vd_bot.engine import BotEngine
from vd_bot.mouse_hold import MouseHoldController

__all__ = [
    "BotEngine",
    "CrosshairOverlay",
    "MouseHoldController",
    "CENTER_X",
    "CENTER_Y",
    "R_MID",
    "R_IN",
    "R_OUT",
    "HARDWARE_LATENCY_SEC",
    "MONITOR_ROI",
]
