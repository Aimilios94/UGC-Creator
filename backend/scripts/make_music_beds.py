"""Cut the licensed music tracks into 30-second beds for compose.py (run by hand, no cost).

    python scripts/make_music_beds.py <folder with the downloaded MP3s>

For each theme in TRACKS it finds the loudest 30-second stretch of the track (skipping
the first seconds, which are often a quiet intro), cuts it, fades it in and out,
normalises loudness to MUSIC_LUFS and strips every tag (and cover art) from the file.
Output: app/music/<theme>.m4a and app/music/music.yaml with the source, licence and cut.
The source files themselves are not kept in the repo.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "app" / "music"
BED_S = 30.0
SKIP_INTRO_S = 4.0
MUSIC_LUFS = -18.0
CHECKED = "2026-11-20"
CC0 = "CC0 1.0 Universal (https://creativecommons.org/publicdomain/zero/1.0/)"

# theme -> (file in the source folder, title, artist, album, FMA track page)
TRACKS = {
    "sport": (
        "HoliznaCC0 - ITS A TRAP.mp3",
        "ITS A TRAP",
        "HoliznaCC0",
        "After Dark",
        "https://freemusicarchive.org/music/holiznacc0/after-dark/its-a-trap-1/",
    ),
    "beauty": (
        "HoliznaCC0 - Ocean Memory.mp3",
        "Ocean Memory",
        "HoliznaCC0",
        "OCEAN MEMORY ( Lo-fi Chill )",
        "https://freemusicarchive.org/music/holiznacc0/ocean-memory-lo-fi-chill/ocean-memory/",
    ),
    "tech": (
        "HoliznaCC0 - Track 1.mp3",
        "Track 1",
        "HoliznaCC0",
        "War ( Game Commission )",
        "https://freemusicarchive.org/music/holiznacc0/war-game-commission/track-1/",
    ),
    "food": (
        "HoliznaCC0 - Toy Box.mp3",
        "Toy Box",
        "HoliznaCC0",
        "Spring Woke Me Up",
        "https://freemusicarchive.org/music/holiznacc0/spring-woke-me-up/toy-box/",
    ),
    "fashion": (
        "Komiku - Everything is groovy (How to move your body).mp3",
        "Everything is groovy (How to move your body)",
        "Komiku",
        "Helice Awesome Dance Adventure !!",
        "https://freemusicarchive.org/music/Komiku/Helice_Awesome_Dance_Adventure_/everything-is-groovy-how-to-move-your-body/",
    ),
}

_M = re.compile(r"t:\s*([\d.]+)\s+TARGET.*?M:\s*(-?[\d.]+|-inf)")


def momentary_loudness(src: Path) -> list[tuple[float, float]]:
    """(time, momentary LUFS) every 100 ms, from ffmpeg's ebur128 filter."""
    proc = subprocess.run(  # noqa: S603 - argument list, no shell
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", "ebur128", "-f", "null", "-"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    points = []
    for m in _M.finditer(proc.stderr):
        value = float(m.group(2)) if m.group(2) != "-inf" else -70.0
        points.append((float(m.group(1)), max(value, -70.0)))
    return points


def best_window(points: list[tuple[float, float]], duration: float) -> float:
    """Start of the 30 s window with the highest mean loudness, on whole seconds."""
    if duration <= BED_S + SKIP_INTRO_S:
        return 0.0
    best_start, best_mean = SKIP_INTRO_S, -1e9
    start = SKIP_INTRO_S
    while start + BED_S <= duration:
        window = [v for t, v in points if start <= t < start + BED_S]
        if window:
            mean = sum(window) / len(window)
            if mean > best_mean:
                best_start, best_mean = start, mean
        start += 1.0
    return best_start


def duration_of(src: Path) -> float:
    out = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


def cut_bed(src: Path, dst: Path, start: float) -> None:
    fade_out = BED_S - 1.5
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{start:.2f}", "-t", f"{BED_S:.2f}", "-i", str(src),
            "-map", "0:a:0", "-vn", "-map_metadata", "-1",
            "-af", f"afade=t=in:d=0.3,afade=t=out:st={fade_out:.2f}:d=1.5,"
            f"loudnorm=I={MUSIC_LUFS}:TP=-1.5:LRA=11",
            "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "128k",
            str(dst),
        ],
        check=True,
    )  # fmt: skip


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    src_dir = Path(argv[0])
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for theme, (fname, title, artist, album, page) in TRACKS.items():
        src = src_dir / fname
        duration = duration_of(src)
        start = best_window(momentary_loudness(src), duration)
        dst = OUT / f"{theme}.m4a"
        cut_bed(src, dst, start)
        manifest[theme] = {
            "file": dst.name,
            "title": title,
            "artist": artist,
            "album": album,
            "source": page,
            "licence": CC0,
            "licence_checked": CHECKED,
            "cut": {"start_s": start, "length_s": BED_S, "loudness_lufs": MUSIC_LUFS},
        }
        print(f"{theme:8s} {title} [{start:.0f}s-{start + BED_S:.0f}s of {duration:.0f}s] -> {dst.name}")
    header = (
        "# Music beds for compose.py: one per theme, cut by scripts/make_music_beds.py.\n"
        "# Every track is CC0 1.0 (public domain): paid ads allowed, no credit needed,\n"
        "# redistribution allowed. Licence check and sources: docs/MUSIC.md.\n"
    )
    (OUT / "music.yaml").write_text(header + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
