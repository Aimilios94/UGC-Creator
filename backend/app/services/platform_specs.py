"""Frame sizes and safe zones per aspect ratio and platform. DB-free.

Safe zones are the parts of the frame that each app's own interface (captions, buttons,
profile row, progress bar) does not cover. Text that compose.py burns in must sit inside
them. The margins are fractions of the frame, an approximation of each app's overlays
for full-screen vertical video (and a small margin for feed formats); the per-platform
checklist in M3 verifies them against each platform's current guidance.
"""

from __future__ import annotations

from dataclasses import dataclass

RATIOS = ("9:16", "1:1", "4:5", "16:9")

# Output frame sizes (width, height) per ratio, 1080 px on the short side.
FRAME = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}


@dataclass(frozen=True)
class SafeZone:
    top: float
    bottom: float
    left: float
    right: float

    def box(self, w: int, h: int) -> tuple[int, int, int, int]:
        """(x0, y0, x1, y1) of the safe area in pixels."""
        return (round(w * self.left), round(h * self.top), round(w * (1 - self.right)), round(h * (1 - self.bottom)))


# Full-screen vertical video: the apps put buttons on the right and caption/profile text at the bottom.
_VERTICAL = {
    "tiktok": SafeZone(top=0.08, bottom=0.20, left=0.06, right=0.15),
    "instagram_reels": SafeZone(top=0.12, bottom=0.20, left=0.06, right=0.12),
    "youtube_shorts": SafeZone(top=0.08, bottom=0.20, left=0.06, right=0.15),
    "facebook": SafeZone(top=0.12, bottom=0.20, left=0.06, right=0.12),
}
_FEED = SafeZone(top=0.05, bottom=0.08, left=0.05, right=0.05)  # 1:1, 4:5, 16:9 in a feed


def safe_zone(platform: str, ratio: str) -> SafeZone:
    if ratio == "9:16":
        return _VERTICAL.get(platform, _VERTICAL["tiktok"])
    return _FEED


def frame_size(ratio: str, scale: float = 1.0) -> tuple[int, int]:
    """Frame size, optionally scaled down (tests); always even, as H.264 needs."""
    w, h = FRAME[ratio]
    return (max(2, round(w * scale / 2) * 2), max(2, round(h * scale / 2) * 2))


def ratio_value(ratio: str) -> float:
    a, b = ratio.split(":")
    return int(a) / int(b)


# A derived ratio is cropped from the master when the crop keeps at least this share of the
# frame; otherwise the master is fitted inside and the rest is filled with a blurred copy.
MIN_CROP_KEEP = 0.75


def crop_keep(master: str, target: str) -> float:
    """Share of the master frame (along the cropped axis) that a centre crop to `target` keeps."""
    m, t = ratio_value(master), ratio_value(target)
    return min(m, t) / max(m, t)


def derive_mode(master: str, target: str) -> str:
    return "crop" if crop_keep(master, target) >= MIN_CROP_KEEP else "pad"
