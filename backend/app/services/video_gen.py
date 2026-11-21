"""Image-to-video per scene from the approved reference image (Kling on fal), async submit and poll.

The clip's aspect ratio comes from the reference image. The model's own audio is not
used: the voiceover and music are added in compose (M2).

Kling takes at most 2,500 characters per prompt. Each clip's text is built here, in one
place, for the render and for the preview the user sees (D30): the scene's movement (never
shortened by the app), the fixed rules, how the shot starts and ends, what stays the same,
then the style and world notes: the user's own notes when they fit, otherwise the short
version the continuity check wrote for this scene.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Scene, render_seconds
from .image_gen import PlannedRender
from .llm_trace import Usage
from .media_cache import cache_key
from .providers.media import InputImage, MediaRequest
from .styles import VIDEO as VIDEO_STYLE
from .styles import VIDEO_NEGATIVE

MAX_PROMPT = 2500  # Kling's prompt limit (fal OpenAPI schema `maxLength`, checked 20 and 21 Nov 2026)
FLOW_MAX = 230  # each of "starts", "ends" and "keep_same" in a clip, at most (D30)
RULES_MAX = 300  # the fixed rules' budget in the clip plan (strategy plan A2): measured worst case, CI-checked

# The fixed rules, v2 (strategy plan A2 and A6, D31): short, and picked by code, never by the writer.
PRODUCT_LINE_PHOTO = "One continuous take, no cuts; product exactly as in the photo."
PRODUCT_LINE_NO_PHOTO = "One continuous take, no cuts; product as described above."
END_IMAGE = "Ends exactly on the given end image; move steadily toward it."
SPEED = "Played {x}x faster: keep moves slow."
FIRST_N = "Only the first {n} seconds are used: fit every beat in them."
TEN_SECONDS = "Spread the beats evenly over 10 seconds."
CONTINUES = "Continues from the previous scene's last frame, same move; no restart."
END_MID = "End mid-movement."


def speed_label(clip_s: int, scene_s: int) -> str:
    """How much faster a clip is played to fit its scene, up to 2 decimals: 1.25, 1.67, 2.5."""
    return f"{clip_s / scene_s:.2f}".rstrip("0").rstrip(".")


def clip_rules(
    *,
    style: str,
    duration_s: int,
    used_s: int,
    idx: int,
    count: int,
    continuous: bool,
    ends_on_next: bool,
    has_photo: bool = True,
) -> str:
    """The fixed rules every clip gets, at the end of its text. At most RULES_MAX characters.
    `duration_s` is the clip Kling makes (5 or 10 s), `used_s` the scene's length on screen."""
    used = min(used_s, duration_s)
    product = PRODUCT_LINE_PHOTO if has_photo else PRODUCT_LINE_NO_PHOTO
    parts = [product, VIDEO_STYLE.get(style, VIDEO_STYLE["realistic"])]
    if ends_on_next:
        parts.append(END_IMAGE)
        if used < duration_s:
            parts.append(SPEED.format(x=speed_label(duration_s, used)))
    elif used < duration_s:
        parts.append(FIRST_N.format(n=used))
    elif duration_s == 10:
        parts.append(TEN_SECONDS)
    if continuous and count > 1:
        # Only in one connected video: separate shots each start from their own picture.
        if idx > 0:
            parts.append(CONTINUES)
        if idx < count - 1:
            parts.append(END_MID)
    return " " + " ".join(parts)  # the leading space joins it to the text before


def worst_rules_len(*, style: str, idx: int, count: int) -> int:
    """The longest the fixed rules can be for this scene, whatever its length and pictures."""
    return max(
        len(clip_rules(style=style, duration_s=render_seconds(u), used_s=u, idx=idx, count=count,
                       continuous=True, ends_on_next=e, has_photo=p))
        for u in range(2, 11)
        for e in (False, True)
        for p in (True, False)
    )  # fmt: skip


def scene_text(scene: Scene) -> str:
    """What the video AI is told happens in the scene: its movement (or, if empty, its description)."""
    return scene.motion_prompt.strip() or scene.description.strip()


def notes_budget(scene: Scene, *, style: str, idx: int, count: int) -> int:
    """Room left for the style and world notes in this scene's clip, with its "Starts" and "Ends"
    lines at their longest ("Same in every scene" is left out when there are notes)."""
    flows = (idx > 0) + (idx < count - 1)
    rules = worst_rules_len(style=style, idx=idx, count=count)
    return MAX_PROMPT - rules - len(scene_text(scene)) - flows * (FLOW_MAX + 10)


def too_long_by(
    scene: Scene, *, style: str, idx: int, count: int, ends_on_next: bool, continuous: bool, has_photo: bool = True
) -> int:
    """How many characters the scene's own text is over Kling's limit with its fixed rules (0 = fits)."""
    rules = clip_rules(
        style=style,
        duration_s=render_seconds(scene.duration_s),
        used_s=scene.duration_s,
        idx=idx,
        count=count,
        continuous=continuous,
        ends_on_next=ends_on_next,
        has_photo=has_photo,
    )
    return max(0, len(scene_text(scene)) + len(rules) - MAX_PROMPT)


def fit_text(text: str, room: int) -> str:
    """Our own generated text cut to the room, at the end of a sentence (or a word) when it is longer."""
    text = text.strip()
    if len(text) <= room:
        return text
    cut = text[:room]
    ends = [m.end() for m in re.finditer(r"[.!?;](?=\s|$)", cut)]
    if ends and ends[-1] > room * 0.5:
        return cut[: ends[-1]].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:") if " " in cut else cut


@dataclass
class ClipText:
    text: str
    chars: int
    limit: int = MAX_PROMPT
    too_long_by: int = 0  # the scene's own text is this much over the limit (the user shortens it)
    notes: str = "none"  # full | short | none: which style and world notes went in


def clip_prompt(
    scene: Scene,
    *,
    idx: int,
    count: int,
    style: str = "realistic",
    notes: str = "",
    continuous: bool = False,
    ends_on_next: bool = False,
    keep_same: str = "",
    render_s: int | None = None,
    has_photo: bool = True,
) -> ClipText:
    """The exact text Kling gets for this scene (at most 2,500 characters). `render_s` is the clip
    the model makes (5 or 10 s; by default the one the scene's length needs)."""
    duration_s = render_s or render_seconds(scene.duration_s)
    rules = clip_rules(
        style=style,
        duration_s=duration_s,
        used_s=scene.duration_s,
        idx=idx,
        count=count,
        continuous=continuous,
        ends_on_next=ends_on_next,
        has_photo=has_photo,
    )
    own = scene_text(scene)
    over = max(0, len(own) + len(rules) - MAX_PROMPT)
    body = own[: MAX_PROMPT - len(rules)]  # cut only if the user sends it on anyway; the page blocks it first
    room = MAX_PROMPT - len(rules) - len(body)
    if continuous:
        for label, text, show in (
            ("Starts", scene.starts, idx > 0),
            ("Ends", scene.ends, idx < count - 1),
            ("Same in every scene", keep_same, not notes.strip()),  # the notes already say it
        ):
            if show and text.strip() and room > 60:
                part = f" {label}: {fit_text(text, min(FLOW_MAX, room - len(label) - 3))}"
                body += part
                room -= len(part)
    used_notes = "none"
    if notes.strip() and room > 80:
        full = f" Style and world: {notes.strip()}"
        if len(full) <= room:
            body, used_notes = body + full, "full"
        elif scene.notes_short.strip():
            label = " Style and world (short): "
            body += label + fit_text(scene.notes_short, room - len(label))
            used_notes = "short"
        else:
            label = " Style and world: "
            body += label + fit_text(notes, room - len(label))
            used_notes = "short"
    prompt = body + rules
    return ClipText(text=prompt, chars=len(prompt), too_long_by=over, notes=used_notes)


def plan_scene_video(
    *,
    model: str,
    scene: Scene,
    duration_s: int,
    reference: InputImage,
    reference_sha256: str,
    style: str = "realistic",
    used_s: int | None = None,
    notes: str = "",
    position: tuple[int, int] = (0, 1),
    continuous: bool = False,
    end_image: InputImage | None = None,
    end_image_sha256: str | None = None,
    keep_same: str = "",
    has_photo: bool = True,
) -> PlannedRender:
    """One clip. In a continuous shot (D30) the clip also gets how it starts and ends (from the
    continuity check) and what stays the same; when the next scene has its own picture, the clip
    ends on that picture (`end_image`), and compose plays the whole clip in the scene's time."""
    if duration_s not in (5, 10):
        raise ValueError("Kling image-to-video accepts 5 or 10 seconds")
    idx, count = position
    shown = scene.model_copy(update={"duration_s": min(used_s or duration_s, duration_s)})
    prompt = clip_prompt(
        shown,
        render_s=duration_s,
        idx=idx,
        count=count,
        style=style,
        notes=notes,
        continuous=continuous,
        ends_on_next=end_image is not None,
        keep_same=keep_same,
        has_photo=has_photo,
    ).text
    arguments = {"prompt": prompt, "duration": str(duration_s), "negative_prompt": VIDEO_NEGATIVE}
    settings: dict = {"duration": duration_s}
    if end_image is not None:
        settings["tail_image_sha256"] = end_image_sha256
    key = cache_key(model=model, prompt=prompt, seed=None, input_sha256=reference_sha256, settings=settings)
    return PlannedRender(
        request=MediaRequest(
            kind="video",
            model=model,
            arguments=arguments,
            input_image=reference,
            image_field="image_url",
            tail_image=end_image,
        ),
        cache_key=key,
        usage=Usage(seconds=duration_s),
    )
