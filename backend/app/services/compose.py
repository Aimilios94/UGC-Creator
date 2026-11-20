"""Compose the finished ad from the rendered scene clips (ffmpeg + Pillow). DB-free.

Plan §8 steps 8-9. For the master ratio and every derived ratio:
- the scene clips are joined (hard cuts, UGC style) into one silent master track; a
  scene is held on its last frame when its voiceover needs more time than the clip;
- each ratio is cropped from the master, or (when a crop would cut too much) the master
  is fitted inside and the rest filled with a blurred copy;
- captions (the voiceover, burned in) and each scene's on-screen headline are laid out by
  us, inside the platform's safe zone, and rendered by libass from an ASS file; the
  brand logo (if any) sits in the top-left corner; a 2-second end card follows;
- audio: the voiceover lines, over the theme's music bed, which is lowered while the
  voice speaks; the clips' own audio is dropped; the mix is normalised to -14 LUFS;
- every exported file carries "AI-generated" metadata (re-encoding drops any marking the
  providers added), plus a cover, one still per scene and a 4:5 carousel.
A ratio whose text cannot fit its safe zone is not exported (`RatioResult.passed`).

All text on screen comes from here, never from the image or video model (models write
made-up lettering; feedback rounds 1-2).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .platform_specs import RATIOS, SafeZone, derive_mode, frame_size, safe_zone

FONTS_DIR = Path(__file__).resolve().parents[1] / "fonts"
FONT_FILES = {  # brand-kit font -> (file, family name libass looks up)
    "Inter": ("Inter.ttf", "Inter"),
    "Montserrat": ("Montserrat.ttf", "Montserrat"),
    "Bebas Neue": ("BebasNeue.ttf", "Bebas Neue"),
    "Playfair Display": ("PlayfairDisplay.ttf", "Playfair Display"),
}

AI_NOTE = "AI-generated: the images, video and voice in this ad were made with AI (UGC Ad Builder)."
DIGITAL_SOURCE_TYPE = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
FPS = 30
VOICE_LEAD_S = 0.15  # the voice starts just after the cut
VOICE_TAIL_S = 0.35  # and ends a little before the next one
MAX_TEMPO = 1.15  # speed a long line up this much before holding the last frame
DUCKED_MUSIC_DB = -6.0

Captions = Literal["bold", "clean", "off"]


class ComposeError(RuntimeError):
    pass


# --- inputs and outputs ------------------------------------------------------------------
@dataclass
class SceneInput:
    clip: Path
    voiceover: str = ""
    headline: str = ""  # the scene's on-screen text
    voice: Path | None = None  # WAV
    voice_s: float = 0.0


@dataclass
class Branding:
    font: str = "Inter"
    primary: str = "#6366f1"
    secondary: str = "#f0abfc"
    background: str = "#0f172a"
    logo: Path | None = None


@dataclass
class ComposeSpec:
    scenes: list[SceneInput]
    master_ratio: str
    platform: str
    cta_text: str
    offer: str = ""
    product_name: str = ""
    end_card_image: Path | None = None  # the product, shown on the end card
    music: Path | None = None
    captions: Captions = "bold"
    branding: Branding = field(default_factory=Branding)
    ratios: tuple[str, ...] = RATIOS
    scale: float = 1.0  # tests render small frames
    end_card_s: float = 2.0
    loudness_lufs: float = -14.0


@dataclass
class SceneTiming:
    start: float
    duration: float
    clip_s: float
    tempo: float
    voice_start: float
    voice_end: float


@dataclass
class TextBox:
    kind: str  # caption | headline | logo | endcard
    box: tuple[int, int, int, int]


@dataclass
class RatioResult:
    ratio: str
    mode: str  # master | crop | pad
    passed: bool
    reason: str = ""
    path: Path | None = None
    size: tuple[int, int] = (0, 0)


@dataclass
class ComposeResult:
    duration_s: float
    timeline: list[SceneTiming]
    ads: list[RatioResult]
    cover: Path
    stills: list[Path]
    carousel: list[Path]

    @property
    def exported(self) -> list[RatioResult]:
        return [r for r in self.ads if r.passed]


# --- small helpers ---------------------------------------------------------------------
def run(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)  # noqa: S603 - argument list, no shell; ffmpeg/ffprobe from PATH
    if proc.returncode != 0:
        raise ComposeError(f"{args[0]} failed: {proc.stderr[-1500:]}")
    return proc.stdout


def probe_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.strip())


def hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def luminance(color: str) -> float:
    r, g, b = (v / 255 for v in hex_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_on(color: str) -> str:
    return "#111111" if luminance(color) > 0.6 else "#ffffff"


def ass_color(color: str, alpha: int = 0) -> str:
    r, g, b = hex_rgb(color)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ass_text(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def load_font(font: str, size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    fname, _ = FONT_FILES.get(font, FONT_FILES["Inter"])
    f = ImageFont.truetype(str(FONTS_DIR / fname), max(8, size))
    if bold:
        try:
            f.set_variation_by_name("Bold")
        except (OSError, ValueError):
            pass  # static font (Bebas Neue)
    return f


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and font.getlength(lines[-1] + " " + word) <= max_w:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def fit_text(
    text: str, font: str, size: int, max_w: int, max_lines: int, min_size: int, bold: bool = True
) -> tuple[int, list[str]] | None:
    """Largest size (from `size` down to `min_size`) at which the text wraps into max_lines
    lines no wider than max_w. Measured with Pillow at the libass font size, which is
    larger than the glyphs libass draws, so the real text is a little smaller."""
    s = size
    while s >= min_size:
        f = load_font(font, s, bold)
        lines = wrap(text, f, max_w)
        if len(lines) <= max_lines and all(f.getlength(line) <= max_w for line in lines):
            return s, lines
        s = int(s * 0.92)
    return None


def inside(box: tuple[int, int, int, int], area: tuple[int, int, int, int]) -> bool:
    return box[0] >= area[0] and box[1] >= area[1] and box[2] <= area[2] and box[3] <= area[3]


# --- timeline ------------------------------------------------------------------------------
def plan_timeline(spec: ComposeSpec) -> list[SceneTiming]:
    out: list[SceneTiming] = []
    t = 0.0
    for scene in spec.scenes:
        clip_s = probe_duration(scene.clip)
        tempo = 1.0
        need = scene.voice_s + VOICE_LEAD_S + VOICE_TAIL_S if scene.voice else 0.0
        if need > clip_s:
            tempo = min(MAX_TEMPO, need / clip_s)
        spoken = scene.voice_s / tempo if scene.voice else 0.0
        duration = max(clip_s, spoken + VOICE_LEAD_S + VOICE_TAIL_S if scene.voice else clip_s)
        vs = t + VOICE_LEAD_S
        out.append(
            SceneTiming(
                start=round(t, 3),
                duration=round(duration, 3),
                clip_s=clip_s,
                tempo=round(tempo, 4),
                voice_start=round(vs, 3),
                voice_end=round(vs + spoken, 3),
            )
        )
        t += duration
    return out


# --- video: silent master ------------------------------------------------------------------
def build_master(spec: ComposeSpec, timeline: list[SceneTiming], size: tuple[int, int], dst: Path) -> None:
    w, h = size
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    parts = []
    for i, (scene, tm) in enumerate(zip(spec.scenes, timeline, strict=True)):
        args += ["-i", str(scene.clip)]
        hold = max(0.0, tm.duration - tm.clip_s) + 0.1
        parts.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={FPS},"
            f"format=yuv420p,tpad=stop_mode=clone:stop_duration={hold:.3f},"
            f"trim=duration={tm.duration:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
    n = len(spec.scenes)
    graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    args += ["-filter_complex", graph, "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast"]
    args += ["-crf", "18", "-pix_fmt", "yuv420p", str(dst)]
    run(args)


# --- audio -----------------------------------------------------------------------------------
def build_audio(spec: ComposeSpec, timeline: list[SceneTiming], total: float, dst: Path) -> None:
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    parts: list[str] = []
    voices: list[str] = []
    idx = 0
    for scene, tm in zip(spec.scenes, timeline, strict=True):
        if scene.voice is None:
            continue
        args += ["-i", str(scene.voice)]
        delay = int(tm.voice_start * 1000)
        tempo = f"atempo={tm.tempo:.4f}," if tm.tempo != 1.0 else ""
        parts.append(
            f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,{tempo}adelay={delay}|{delay}[vo{idx}]"
        )
        voices.append(f"[vo{idx}]")
        idx += 1
    music_idx = None
    if spec.music is not None:
        args += ["-stream_loop", "-1", "-i", str(spec.music)]
        music_idx = idx
        idx += 1
    fade_at = max(0.0, total - 1.0)
    if voices:
        parts.append("".join(voices) + f"amix=inputs={len(voices)}:normalize=0:duration=longest,apad[voall]")
    if voices and music_idx is not None:
        parts.append("[voall]asplit=2[vo_mix][vo_key]")
        parts.append(
            f"[{music_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},"
            f"volume={DUCKED_MUSIC_DB}dB,afade=t=out:st={fade_at:.3f}:d=1[mus]"
        )
        parts.append("[mus][vo_key]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[duck]")
        parts.append("[duck][vo_mix]amix=inputs=2:normalize=0:duration=first[mix]")
    elif voices:
        parts.append("[voall]anull[mix]")
    elif music_idx is not None:
        parts.append(
            f"[{music_idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},"
            f"afade=t=out:st={fade_at:.3f}:d=1[mix]"
        )
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        parts.append(f"[{idx}:a]atrim=0:{total:.3f}[mix]")
    parts.append(
        f"[mix]atrim=0:{total:.3f},loudnorm=I={spec.loudness_lufs}:TP=-1.5:LRA=11,"
        "aformat=sample_rates=48000:channel_layouts=stereo[a]"
    )
    args += ["-filter_complex", ";".join(parts), "-map", "[a]", "-t", f"{total:.3f}", "-c:a", "aac", "-b:a", "160k"]
    run(args + [str(dst)])


# --- text layout (shared by video captions, stills and the end card) ---------------------------
@dataclass
class Layout:
    ok: bool
    reason: str
    events: list[str]  # ASS dialogue lines
    styles: list[str]
    boxes: list[TextBox]
    logo_box: tuple[int, int, int, int] | None


def _logo_size(logo: Path, w: int, h: int) -> tuple[int, int]:
    with Image.open(logo) as im:
        lw = round(min(w, h) * 0.18)
        return lw, max(1, round(im.height * lw / im.width))


def _headline_top(area: tuple[int, int, int, int], logo_box) -> int:
    return (logo_box[3] + round((area[3] - area[1]) * 0.02)) if logo_box else area[1]


def _ts(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _chunks(text: str, size: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def layout_text(spec: ComposeSpec, timeline: list[SceneTiming], w: int, h: int, zone: SafeZone) -> Layout:
    b = spec.branding
    area = zone.box(w, h)
    aw, ah = area[2] - area[0], area[3] - area[1]
    short = min(w, h)
    _, family = FONT_FILES.get(b.font, FONT_FILES["Inter"])
    boxes: list[TextBox] = []
    events: list[str] = []

    logo_box = None
    if b.logo is not None:
        lw, lh = _logo_size(b.logo, w, h)
        logo_box = (area[0], area[1], area[0] + lw, area[1] + lh)
        boxes.append(TextBox("logo", logo_box))
        if not inside(logo_box, area):
            return Layout(False, "the logo does not fit the safe zone", [], [], boxes, logo_box)

    head_fill = b.primary
    head_text = text_on(head_fill)
    cap_size0 = round(short * 0.075)
    head_size0 = round(short * 0.072)
    styles = [
        # Name, Fontname, Fontsize, Primary, Secondary, Outline, Back, Bold, Italic, Underline, StrikeOut,
        # ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Enc
        f"Style: Caption,{family},{cap_size0},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        f"{-1 if spec.captions == 'bold' else 0},0,0,0,100,100,0,0,1,{max(1, round(cap_size0 * 0.09))},0,5,0,0,0,1",
        f"Style: Headline,{family},{head_size0},{ass_color(head_text)},&H00FFFFFF,{ass_color(head_fill)},"
        f"{ass_color(head_fill)},-1,0,0,0,100,100,0,0,3,{max(1, round(head_size0 * 0.22))},0,5,0,0,0,1",
    ]

    cx = (area[0] + area[2]) // 2
    head_top = _headline_top(area, logo_box)
    cap_center = area[1] + round(ah * 0.78)
    for scene, tm in zip(spec.scenes, timeline, strict=True):
        if scene.headline.strip():
            fit = fit_text(scene.headline, b.font, head_size0, round(aw * 0.86), 2, round(short * 0.035))
            if fit is None:
                return Layout(False, f"the headline does not fit: {scene.headline!r}", [], styles, boxes, logo_box)
            size, lines = fit
            pad = round(size * 0.22)
            bh = round(len(lines) * size * 1.25) + 2 * pad
            bw = round(max(load_font(b.font, size).getlength(x) for x in lines)) + 2 * pad
            box = (cx - bw // 2, head_top, cx + (bw + 1) // 2, head_top + bh)
            boxes.append(TextBox("headline", box))
            if not inside(box, area):
                return Layout(False, "the headline does not fit the safe zone", [], styles, boxes, logo_box)
            y = head_top + bh // 2
            text = "\\N".join(ass_text(x) for x in lines)
            events.append(
                f"Dialogue: 1,{_ts(tm.start)},{_ts(tm.start + tm.duration)},Headline,,0,0,0,,"
                f"{{\\an5\\pos({cx},{y})\\fs{size}}}{text}"
            )
        if spec.captions == "off" or not scene.voiceover.strip() or tm.voice_end <= tm.voice_start:
            continue
        pages = _chunks(scene.voiceover, 3) if spec.captions == "bold" else [scene.voiceover]
        if spec.captions == "clean":
            fit = fit_text(scene.voiceover, b.font, cap_size0, round(aw * 0.9), 4, round(short * 0.03), bold=False)
            if fit is None:
                return Layout(False, "the caption does not fit the safe zone", [], styles, boxes, logo_box)
            size, lines = fit
            pages = [" ".join(lines[i : i + 2]) for i in range(0, len(lines), 2)]
        weights = [max(1, len(p)) for p in pages]
        span = tm.voice_end - tm.voice_start
        t0 = tm.voice_start
        for page, wgt in zip(pages, weights, strict=True):
            t1 = t0 + span * wgt / sum(weights)
            fit = fit_text(
                page, b.font, cap_size0, round(aw * 0.9), 2, round(short * 0.03), bold=spec.captions == "bold"
            )
            if fit is None:
                return Layout(False, f"the caption does not fit: {page!r}", [], styles, boxes, logo_box)
            size, lines = fit
            bh = round(len(lines) * size * 1.25)
            bw = round(max(load_font(b.font, size, spec.captions == "bold").getlength(x) for x in lines))
            box = (cx - bw // 2, cap_center - bh // 2, cx + (bw + 1) // 2, cap_center + (bh + 1) // 2)
            boxes.append(TextBox("caption", box))
            if not inside(box, area):
                return Layout(False, "the caption does not fit the safe zone", [], styles, boxes, logo_box)
            text = "\\N".join(ass_text(x) for x in lines)
            events.append(
                f"Dialogue: 0,{_ts(t0)},{_ts(t1)},Caption,,0,0,0,,{{\\an5\\pos({cx},{cap_center})\\fs{size}}}{text}"
            )
            t0 = t1
    return Layout(True, "", events, styles, boxes, logo_box)


def write_ass(layout: Layout, w: int, h: int, dst: Path) -> None:
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {w}",
        f"PlayResY: {h}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        *layout.styles,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        *layout.events,
    ]
    dst.write_text("\n".join(head) + "\n", encoding="utf-8")


# --- images: end card, stills, carousel, cover ------------------------------------------------
def _fit_into(img: Image.Image, w: int, h: int, mode: str) -> Image.Image:
    """mode crop: fill and centre-crop; pad: fit inside a blurred, filled copy."""
    img = img.convert("RGB")
    cover = max(w / img.width, h / img.height)
    filled = img.resize((max(1, round(img.width * cover)), max(1, round(img.height * cover))), Image.LANCZOS)
    left, top = (filled.width - w) // 2, (filled.height - h) // 2
    filled = filled.crop((left, top, left + w, top + h))
    if mode == "crop":
        return filled
    bg = filled.filter(ImageFilter.GaussianBlur(radius=max(4, min(w, h) // 25)))
    fit = min(w / img.width, h / img.height)
    fg = img.resize((max(1, round(img.width * fit)), max(1, round(img.height * fit))), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return bg


def _draw_lines(draw, lines, font, cx, top, fill, line_h):
    y = top
    for line in lines:
        draw.text((cx, y + line_h // 2), line, font=font, fill=fill, anchor="mm")
        y += line_h


def render_end_card(spec: ComposeSpec, w: int, h: int, zone: SafeZone) -> tuple[Image.Image, bool, str]:
    b = spec.branding
    area = zone.box(w, h)
    aw, ah = area[2] - area[0], area[3] - area[1]
    short = min(w, h)
    card = Image.new("RGB", (w, h), hex_rgb(b.background))
    draw = ImageDraw.Draw(card)
    fg = text_on(b.background)
    cx = (area[0] + area[2]) // 2
    y = area[1]
    if b.logo is not None:
        with Image.open(b.logo) as logo:
            lw, lh = _logo_size(b.logo, w, h)
            logo = logo.convert("RGBA").resize((lw, lh), Image.LANCZOS)
            card.paste(logo, (cx - lw // 2, y), logo)
            y += lh + round(ah * 0.03)
    # text block sizes first, so the product image takes the space that is left
    offer_fit = None
    if spec.offer.strip():
        offer_fit = fit_text(spec.offer, b.font, round(short * 0.06), round(aw * 0.9), 3, round(short * 0.03))
        if offer_fit is None:
            return card, False, "the offer does not fit the end card"
    cta_fit = fit_text(
        spec.cta_text or "Shop now", b.font, round(short * 0.065), round(aw * 0.8), 1, round(short * 0.03)
    )
    if cta_fit is None:
        return card, False, "the call to action does not fit the end card"
    offer_h = round(len(offer_fit[1]) * offer_fit[0] * 1.25) if offer_fit else 0
    btn_pad = round(cta_fit[0] * 0.55)
    btn_h = round(cta_fit[0] * 1.25) + 2 * btn_pad
    gap = round(ah * 0.03)
    image_h = area[3] - y - offer_h - btn_h - 3 * gap
    if spec.end_card_image is not None and image_h > ah * 0.2:
        with Image.open(spec.end_card_image) as prod:
            prod = prod.convert("RGB")
            fit = min(aw * 0.85 / prod.width, image_h / prod.height)
            pw, ph = max(1, round(prod.width * fit)), max(1, round(prod.height * fit))
            prod = prod.resize((pw, ph), Image.LANCZOS)
            mask = Image.new("L", (pw, ph), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=round(short * 0.03), fill=255)
            card.paste(prod, (cx - pw // 2, y + gap), mask)
            y += ph + 2 * gap
    else:
        y = area[1] + (ah - offer_h - btn_h - gap) // 2
    if offer_fit:
        size, lines = offer_fit
        _draw_lines(draw, lines, load_font(b.font, size), cx, y, fg, round(size * 1.25))
        y += offer_h + gap
    size, lines = cta_fit
    font = load_font(b.font, size)
    bw = round(font.getlength(lines[0])) + 4 * btn_pad
    btn = (cx - bw // 2, y, cx + bw // 2, y + btn_h)
    if not inside(btn, area):
        return card, False, "the end card does not fit the safe zone"
    draw.rounded_rectangle(btn, radius=btn_h // 2, fill=hex_rgb(b.primary))
    draw.text((cx, y + btn_h // 2), lines[0], font=font, fill=text_on(b.primary), anchor="mm")
    return card, True, ""


def draw_headline(img: Image.Image, text: str, spec: ComposeSpec, zone: SafeZone) -> Image.Image:
    if not text.strip():
        return img
    b = spec.branding
    w, h = img.size
    area = zone.box(w, h)
    short = min(w, h)
    logo_box = None
    if b.logo is not None:
        lw, lh = _logo_size(b.logo, w, h)
        logo_box = (area[0], area[1], area[0] + lw, area[1] + lh)
        with Image.open(b.logo) as logo:
            logo = logo.convert("RGBA").resize((lw, lh), Image.LANCZOS)
            img.paste(logo, (area[0], area[1]), logo)
    fit = fit_text(text, b.font, round(short * 0.07), round((area[2] - area[0]) * 0.86), 2, round(short * 0.035))
    if fit is None:
        return img
    size, lines = fit
    font = load_font(b.font, size)
    pad = round(size * 0.3)
    line_h = round(size * 1.25)
    bw = round(max(font.getlength(x) for x in lines)) + 2 * pad
    bh = len(lines) * line_h + 2 * pad
    cx = (area[0] + area[2]) // 2
    top = _headline_top(area, logo_box)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((cx - bw // 2, top, cx + bw // 2, top + bh), radius=pad, fill=hex_rgb(b.primary))
    _draw_lines(draw, lines, font, cx, top + pad, text_on(b.primary), line_h)
    return img


def frame_at(video: Path, t: float, dst: Path) -> Image.Image:
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video)]
        + ["-frames:v", "1", str(dst)])  # fmt: skip
    with Image.open(dst) as im:
        return im.convert("RGB")


# --- AI metadata ---------------------------------------------------------------------------------
def _xmp_packet() -> bytes:
    return (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<Iptc4xmpExt:DigitalSourceType>{DIGITAL_SOURCE_TYPE}</Iptc4xmpExt:DigitalSourceType>"
        f'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">{AI_NOTE}</rdf:li></rdf:Alt></dc:description>'
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    ).encode()


def save_jpeg(img: Image.Image, dst: Path) -> Path:
    """JPEG with the AI marking in EXIF (ImageDescription, Software) and XMP (IPTC DigitalSourceType)."""
    exif = Image.Exif()
    exif[0x010E] = AI_NOTE  # ImageDescription
    exif[0x0131] = "UGC Ad Builder (AI-generated)"  # Software
    img.convert("RGB").save(dst, "JPEG", quality=90, exif=exif.tobytes(), xmp=_xmp_packet())
    return dst


def mp4_metadata_args(title: str) -> list[str]:
    return [
        "-map_metadata", "-1",
        "-metadata", f"title={title}",
        "-metadata", f"comment={AI_NOTE}",
        "-metadata", f"description={AI_NOTE}",
        "-metadata", "ai_generated=true",
        "-metadata", f"digital_source_type={DIGITAL_SOURCE_TYPE}",
        "-movflags", "+faststart+use_metadata_tags",
    ]  # fmt: skip


def read_ai_marking(path: Path) -> dict:
    """What a viewer or platform can read back from an exported file (used by the checks)."""
    if path.suffix.lower() == ".mp4":
        out = run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)])
        tags = {k.lower(): v for k, v in json.loads(out).get("format", {}).get("tags", {}).items()}
        return {
            "ai_generated": tags.get("ai_generated") == "true" and "AI-generated" in tags.get("comment", ""),
            "digital_source_type": tags.get("digital_source_type", ""),
        }
    with Image.open(path) as im:
        exif = im.getexif()
        xmp = im.info.get("xmp", b"")
        xmp = xmp.decode("utf-8", "ignore") if isinstance(xmp, bytes) else str(xmp)
        return {
            "ai_generated": "AI-generated" in str(exif.get(0x010E, "")) and DIGITAL_SOURCE_TYPE in xmp,
            "digital_source_type": DIGITAL_SOURCE_TYPE if DIGITAL_SOURCE_TYPE in xmp else "",
        }


# --- one ratio -----------------------------------------------------------------------------------
def _transform(mode: str, w: int, h: int) -> str:
    if mode in ("master", "crop"):
        return f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[base]"
    blur = max(4, min(w, h) // 25)
    return (
        f"[0:v]split=2[bg0][fg0];[bg0]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"gblur=sigma={blur}[bg];[fg0]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]"
    )


def render_ratio(
    spec: ComposeSpec,
    timeline: list[SceneTiming],
    work: Path,
    master: Path,
    audio: Path,
    ratio: str,
    total: float,
) -> RatioResult:
    w, h = frame_size(ratio, spec.scale)
    mode = "master" if ratio == spec.master_ratio else derive_mode(spec.master_ratio, ratio)
    zone = safe_zone(spec.platform, ratio)
    tag = ratio.replace(":", "x")
    layout = layout_text(spec, timeline, w, h, zone)
    if not layout.ok:
        return RatioResult(ratio, mode, False, layout.reason, size=(w, h))
    card, ok, reason = render_end_card(spec, w, h, zone)
    if not ok:
        return RatioResult(ratio, mode, False, reason, size=(w, h))
    card_png = work / f"endcard_{tag}.png"
    card.save(card_png)
    ass = work / f"captions_{tag}.ass"
    write_ass(layout, w, h, ass)

    scenes_s = sum(t.duration for t in timeline)
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(master)]
    args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{spec.end_card_s:.3f}", "-i", card_png.name]
    args += ["-i", str(audio)]
    graph = [_transform(mode, w, h), f"[base]subtitles=filename={ass.name}:fontsdir=fonts[sub]"]
    last = "[sub]"
    if spec.branding.logo is not None and layout.logo_box is not None:
        args += ["-i", str(spec.branding.logo)]
        lb = layout.logo_box
        graph.append(f"[3:v]scale={lb[2] - lb[0]}:{lb[3] - lb[1]},format=rgba,colorchannelmixer=aa=0.92[logo]")
        graph.append(f"{last}[logo]overlay={lb[0]}:{lb[1]}:enable='lt(t,{scenes_s:.3f})'[wm]")
        last = "[wm]"
    graph.append(f"{last}fps={FPS},format=yuv420p[sv]")
    graph.append(f"[1:v]scale={w}:{h},setsar=1,fps={FPS},format=yuv420p[ec]")
    graph.append("[sv][ec]concat=n=2:v=1:a=0[v]")
    dst = work / f"ad_{tag}.mp4"
    args += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "2:a", "-t", f"{total:.3f}"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy"]
    args += mp4_metadata_args(f"{spec.product_name} ad ({ratio})".strip())
    run(args + [dst.name], cwd=work)
    return RatioResult(ratio, mode, True, "", path=dst, size=(w, h))


# --- the whole ad --------------------------------------------------------------------------------
def compose(spec: ComposeSpec, work: Path) -> ComposeResult:
    if not spec.scenes:
        raise ComposeError("no scenes to compose")
    work.mkdir(parents=True, exist_ok=True)
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    for fname, _ in FONT_FILES.values():
        shutil.copyfile(FONTS_DIR / fname, fonts / fname)

    timeline = plan_timeline(spec)
    scenes_s = sum(t.duration for t in timeline)
    total = round(scenes_s + spec.end_card_s, 3)
    mw, mh = frame_size(spec.master_ratio, spec.scale)
    master = work / "master_scenes.mp4"
    build_master(spec, timeline, (mw, mh), master)
    audio = work / "audio.m4a"
    build_audio(spec, timeline, total, audio)

    ratios = [spec.master_ratio] + [r for r in spec.ratios if r != spec.master_ratio]
    ads = [render_ratio(spec, timeline, work, master, audio, r, total) for r in ratios]
    if not ads[0].passed:
        raise ComposeError(f"the master ratio {spec.master_ratio} failed its safe-zone check: {ads[0].reason}")

    zone = safe_zone(spec.platform, spec.master_ratio)
    stills: list[Path] = []
    raw_frames: list[Image.Image] = []
    for i, (scene, tm) in enumerate(zip(spec.scenes, timeline, strict=True)):
        frame = frame_at(master, tm.start + min(tm.duration / 2, tm.clip_s / 2), work / f"frame_{i}.png")
        raw_frames.append(frame.copy())
        stills.append(save_jpeg(draw_headline(frame, scene.headline, spec, zone), work / f"still_{i + 1}.jpg"))
    cover_frame = frame_at(master, min(0.3, timeline[0].duration / 2), work / "frame_cover.png")
    cover = save_jpeg(draw_headline(cover_frame, spec.scenes[0].headline, spec, zone), work / "cover.jpg")

    cw, ch = frame_size("4:5", spec.scale)
    czone = safe_zone(spec.platform, "4:5")
    mode = "master" if spec.master_ratio == "4:5" else derive_mode(spec.master_ratio, "4:5")
    carousel: list[Path] = []
    for i, (scene, frame) in enumerate(zip(spec.scenes, raw_frames, strict=True)):
        slide = _fit_into(frame, cw, ch, "crop" if mode in ("master", "crop") else "pad")
        carousel.append(save_jpeg(draw_headline(slide, scene.headline, spec, czone), work / f"carousel_{i + 1}.jpg"))
    end_slide, ok, _ = render_end_card(spec, cw, ch, czone)
    if ok:
        carousel.append(save_jpeg(end_slide, work / f"carousel_{len(spec.scenes) + 1}.jpg"))
    return ComposeResult(duration_s=total, timeline=timeline, ads=ads, cover=cover, stills=stills, carousel=carousel)
