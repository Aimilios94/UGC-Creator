"""compose.py on tiny fixture clips with real ffmpeg (plan §15), the ratio and safe-zone maths,
the music beds, and the voice stage's spend rules."""

from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app import repository as repo
from app import worker
from app.services import compose as C
from app.services.music import bed_for, manifest
from app.services.output_checks import check_compose
from app.services.platform_specs import crop_keep, derive_mode, frame_size, safe_zone
from app.services.providers.media import MOCK_CLIP
from app.services.providers.voice import MockVoice, VoiceRequest
from app.services.voice import instructions_for, plan_voice, usage_for
from conftest import BRIEF
from helpers import approve, create_job

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# --- ratio and safe-zone maths -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("master", "target", "mode"),
    [("9:16", "4:5", "pad"), ("9:16", "1:1", "pad"), ("9:16", "16:9", "pad"), ("4:5", "1:1", "crop"),
     ("1:1", "4:5", "crop"), ("16:9", "9:16", "pad"), ("9:16", "9:16", "crop")],
)  # fmt: skip
def test_a_derived_ratio_is_cropped_only_when_the_crop_keeps_enough(master, target, mode):
    assert derive_mode(master, target) == mode
    assert 0 < crop_keep(master, target) <= 1


def test_frame_sizes_and_safe_zones():
    assert frame_size("9:16") == (1080, 1920) and frame_size("16:9") == (1920, 1080)
    assert frame_size("4:5", 0.25) == (270, 338)  # even sides for H.264
    x0, y0, x1, y1 = safe_zone("tiktok", "9:16").box(1080, 1920)
    assert (x0, y0) == (65, 154) and x1 < 1080 - 150 and y1 == 1536  # buttons on the right, captions at the bottom
    assert safe_zone("tiktok", "1:1") == safe_zone("instagram_reels", "1:1")  # feed formats share a margin


# --- music beds ------------------------------------------------------------------------------------
def test_every_theme_has_a_licensed_cc0_bed():
    beds = manifest()
    assert set(beds) == {"sport", "beauty", "tech", "food", "fashion"}
    for theme, entry in beds.items():
        assert entry["licence"].startswith("CC0 1.0") and entry["source"].startswith("https://freemusicarchive.org/")
        path = bed_for(theme, "food")
        assert path.exists() and C.probe_duration(path) == pytest.approx(30, abs=0.1)
    assert bed_for(None, "food").name == "food.m4a"


# --- compose on fixture clips ----------------------------------------------------------------------
LINES = ["Stop scrolling: this is Grip Socks Pro.", "Here is how it works, in one step.", "Get yours today."]
HEADS = ["Meet Grip Socks Pro", "How it works", "10% off with code KICK10"]


def _logo(path: Path) -> Path:
    img = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    img.paste((255, 120, 0, 255), (10, 10, 290, 110))
    img.save(path)
    return path


def _spec(tmp: Path, **kw) -> C.ComposeSpec:
    voice = MockVoice()
    scenes = []
    for i, (line, head) in enumerate(zip(LINES, HEADS, strict=True)):
        clip = voice.synthesize(VoiceRequest(model="m", text=line, voice="marin"))
        wav = tmp / f"v{i}.wav"
        wav.write_bytes(clip.wav)
        scenes.append(C.SceneInput(clip=MOCK_CLIP, voiceover=line, headline=head, voice=wav, voice_s=clip.duration_s))
    product = tmp / "product.jpg"
    Image.new("RGB", (400, 500), (30, 120, 200)).save(product)
    base = dict(
        scenes=scenes,
        master_ratio="9:16",
        platform="tiktok",
        cta_text="Shop now",
        offer="10% off with code KICK10",
        product_name="Grip Socks Pro",
        end_card_image=product,
        music=bed_for("sport", "food"),
        branding=C.Branding(font="Bebas Neue", primary="#ff6600", logo=_logo(tmp / "logo.png")),
        scale=0.25,
    )
    base.update(kw)
    return C.ComposeSpec(**base)


def _loudness(path: Path) -> float:
    err = subprocess.run(  # noqa: S603
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],  # noqa: S607
        capture_output=True,
        text=True,
    ).stderr  # fmt: skip
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", err)[-1])


def test_compose_builds_every_ratio_with_voice_music_captions_and_end_card(tmp_path):
    spec = _spec(tmp_path)
    result = C.compose(spec, tmp_path / "out")
    assert [r.ratio for r in result.exported] == ["9:16", "1:1", "4:5", "16:9"]
    assert {r.ratio: r.mode for r in result.ads} == {"9:16": "master", "1:1": "pad", "4:5": "pad", "16:9": "pad"}
    # each 1 s clip is held on its last frame until its voiceover line has finished
    for tm in result.timeline:
        assert tm.duration > tm.clip_s and 1.0 < tm.tempo <= C.MAX_TEMPO
        assert tm.voice_end <= tm.start + tm.duration
    assert result.duration_s == pytest.approx(sum(t.duration for t in result.timeline) + spec.end_card_s)
    checks = check_compose(spec, result)
    assert all(c["passed"] for c in checks), checks
    assert _loudness(result.exported[0].path) == pytest.approx(-14, abs=1.5)
    ass = (tmp_path / "out" / "captions_9x16.ass").read_text(encoding="utf-8")
    assert "STOP SCROLLING" not in ass and "Stop scrolling: this" in ass  # the voiceover, in chunks
    assert "Meet Grip Socks Pro" in ass and "Bebas Neue" in ass


def test_every_exported_file_carries_ai_metadata(tmp_path):
    """Guardrail (M2): every exported file carries "AI-generated" metadata."""
    result = C.compose(_spec(tmp_path), tmp_path / "out")
    files = [r.path for r in result.exported] + [result.cover, *result.stills, *result.carousel]
    assert len(files) == 4 + 1 + 3 + 4
    for path in files:
        marking = C.read_ai_marking(path)
        assert marking["ai_generated"] and marking["digital_source_type"] == C.DIGITAL_SOURCE_TYPE, path.name


def test_text_layout_stays_inside_the_safe_zone(tmp_path):
    spec = _spec(tmp_path)
    timeline = C.plan_timeline(spec)
    for ratio in ("9:16", "1:1", "4:5", "16:9"):
        w, h = frame_size(ratio)
        zone = safe_zone("tiktok", ratio)
        layout = C.layout_text(spec, timeline, w, h, zone)
        assert layout.ok, (ratio, layout.reason)
        assert layout.boxes and all(C.inside(b.box, zone.box(w, h)) for b in layout.boxes)
        kinds = {b.kind for b in layout.boxes}
        assert {"logo", "headline", "caption"} <= kinds


def test_text_that_cannot_fit_fails_the_check_and_the_master_is_never_exported_broken(tmp_path):
    spec = _spec(tmp_path)
    spec.scenes[0].headline = "Supercalifragilisticexpialidocious" * 3  # one word, no place to wrap
    layout = C.layout_text(spec, C.plan_timeline(spec), 1080, 1920, safe_zone("tiktok", "9:16"))
    assert not layout.ok and "headline" in layout.reason
    with pytest.raises(C.ComposeError, match="safe-zone"):
        C.compose(spec, tmp_path / "out")


def test_compose_without_music_voice_or_captions_still_has_an_audio_track(tmp_path):
    spec = _spec(tmp_path, music=None, captions="off", ratios=("9:16",))
    for scene in spec.scenes:
        scene.voice, scene.voice_s = None, 0.0
    result = C.compose(spec, tmp_path / "out")
    checks = check_compose(spec, result)
    assert checks[0]["audio_track"] and checks[0]["passed"]
    assert all(t.duration == pytest.approx(t.clip_s) for t in result.timeline)  # nothing to wait for
    ass = (tmp_path / "out" / "captions_9x16.ass").read_text(encoding="utf-8")
    assert "Caption,,0,0,0" not in ass  # no caption events, headlines only


def test_end_card_shows_offer_and_cta_with_readable_contrast(tmp_path):
    spec = _spec(tmp_path, branding=C.Branding(background="#ffffff", primary="#ffee00"))
    card, ok, _ = C.render_end_card(spec, 1080, 1920, safe_zone("tiktok", "9:16"))
    assert ok and card.size == (1080, 1920)
    assert C.text_on("#ffffff") == "#111111" and C.text_on("#0f172a") == "#ffffff"


def test_jpeg_metadata_survives_a_round_trip(tmp_path):
    path = C.save_jpeg(Image.new("RGB", (64, 64), (1, 2, 3)), tmp_path / "x.jpg")
    with Image.open(io.BytesIO(path.read_bytes())) as im:
        assert "AI-generated" in im.getexif()[0x010E]


# --- voice planning and the voice stage --------------------------------------------------------------
def test_voice_cost_is_estimated_high_and_recorded_from_the_real_length():
    planned = plan_voice(
        model="gpt-4o-mini-tts", text="Stop scrolling: this is Grip Socks Pro.", voice="marin", tone=None
    )
    assert planned.request.instructions == instructions_for(None) and "not an announcer" in planned.request.instructions
    real = usage_for(planned.request, 2.1)
    assert planned.usage.output_tokens > real.output_tokens  # the estimate is on the high side
    assert instructions_for("energetic") != instructions_for("calm")
    same = plan_voice(model="gpt-4o-mini-tts", text="Stop scrolling: this is Grip Socks Pro.", voice="marin", tone=None)
    other = plan_voice(
        model="gpt-4o-mini-tts", text="Stop scrolling: this is Grip Socks Pro.", voice="cedar", tone=None
    )
    assert same.cache_key == planned.cache_key != other.cache_key


def test_a_voice_failure_stops_the_job_before_any_video_is_paid(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    approve(client, session_id, job["id"])

    def broken(req):
        raise RuntimeError("tts model not allowed for this project")

    ctx.voice.synthesize = broken
    worker.run_once(ctx)
    assert ctx.media.submits == []  # nothing rendered
    with ctx.db.tx() as c:
        rows = c.execute("select kind, status from llm_calls where job_id = %s", (job["id"],)).fetchall()
    assert [r["status"] for r in rows if r["kind"] == "tts"] == ["released"]


def test_voice_lines_are_paid_once_and_reused_from_the_cache(client, ctx, session_id, photo_bytes):
    first = create_job(client, session_id, photo_bytes).json()
    approve(client, session_id, first["id"])
    worker.run_once(ctx)
    assert len(ctx.voice.requests) == 3
    # The same brief again: the same lines with the same voice come from the media cache.
    second = create_job(client, session_id, photo_bytes).json()
    approve(client, session_id, second["id"])
    worker.run_once(ctx)
    assert len(ctx.voice.requests) == 3
    with ctx.db.tx() as c:
        hits = c.execute(
            "select count(*) as n from llm_calls where job_id = %s and kind = 'tts' and cache_hit", (second["id"],)
        ).fetchone()["n"]
    assert hits == 3


def test_brief_choices_reach_compose(client, ctx, session_id, photo_bytes):
    brief = {**BRIEF, "voice": "onyx", "music": "none", "captions": "clean", "theme": "tech"}
    job = create_job(client, session_id, photo_bytes, brief=brief).json()
    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    assert {r.voice for r in ctx.voice.requests} == {"onyx"}
    view = client.get(f"/jobs/{job['id']}", headers={"X-Session-Id": session_id}).json()
    assert view["status"] == "done" and view["variants"][0]["ratios"]
    assert repo.get_stage_run(ctx.db, job["id"], "compose")["status"] == "done"
    bad = create_job(client, session_id, photo_bytes, brief={**BRIEF, "voice": "robot"})
    assert bad.status_code == 422
