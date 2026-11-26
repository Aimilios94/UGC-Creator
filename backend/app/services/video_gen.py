"""Image-to-video per scene from the approved reference image (Kling on fal), async submit and poll.

The clip's aspect ratio comes from the reference image. The model's own audio is not
used: the voiceover and music are added in compose (M2).

Kling takes at most 2,500 characters per prompt. Each clip's text is built here, in one
place, for the render and for the preview the user sees (D30). Since phase 4 of the strategy
plan (D31) it is built from the structure's slots with a budget per part (`build_clip`): the
movement (the user's action word for word, unless the writer swapped a Kling weak spot, A1),
who is in the shot and the product, how it starts and ends, the place and look, the user's
notes when there is room, then the fixed rules; at most 2,310 characters. "Never" and "Avoid"
go to Kling's separate negative prompt. Without a structure the older build is used: the
scene's movement, how it starts and ends, what stays the same and the notes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
    flows_in: bool = True,
    flows_out: bool = True,
) -> str:
    """The fixed rules every clip gets, at the end of its text. At most RULES_MAX characters.
    `duration_s` is the clip Kling makes (5 or 10 s), `used_s` the scene's length on screen.
    `flows_in` / `flows_out`: the shot flows on from the one before / into the one after (D32); a
    cut on either side drops that continue line."""
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
        if idx > 0 and flows_in:
            parts.append(CONTINUES)
        if idx < count - 1 and flows_out:
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
class ClipPart:
    name: str
    chars: int
    budget: int


@dataclass
class ClipText:
    text: str
    chars: int
    limit: int = MAX_PROMPT
    too_long_by: int = 0  # the scene's own text is this much over the limit (the user shortens it)
    notes: str = "none"  # full | short | none: which style and world notes went in
    parts: list[ClipPart] = field(default_factory=list)  # built from the structure: each part and its budget
    negative: str = VIDEO_NEGATIVE  # Kling's separate negative prompt field
    shorten_field: str = "motion_prompt"  # the scene field "Shorten it for me" rewrites


# --- the clip builder (strategy plan phase 4, D31) ----------------------------------------------
# Every clip is built from the structure's slots, most important part first, each part within its
# budget, so the text is planned to fit instead of cut afterwards. The budgets add up to 2,310.
TOTAL_MAX = 2310
MOVE_MAX = 1000  # the movement: the action, the camera and the timeline
MOVE_BORROW_MAX = 1400  # the movement may borrow what the other parts leave unused, up to this
WHO_MAX = 400  # who is in the shot and the product
FLOW_PART_MAX = 180  # each of "Starts" and "Ends"
FLOW_PART_SHORT = 120  # each, when the clip would pass the total
PLACE_MAX = 250  # place, light, look
BUDGETS = {"movement": MOVE_MAX, "who": WHO_MAX, "start_end": 2 * FLOW_PART_MAX, "place": PLACE_MAX, "rules": RULES_MAX}
TIME_MARK = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:-|–|to)\s*\d+(?:[.,]\d+)?\s*s\b|\b\d{1,2}:\d{2}\b", re.I)


_NO = re.compile(r"^\s*(?:no|never|avoid|without|not)\s+(?:any\s+)?", re.I)


def _as_avoid(text: str) -> str:
    """ "no bright daytime, no staged smiles" -> "bright daytime, staged smiles": the field already
    means "avoid", so a "no" in it would be a double negative."""
    return ", ".join(x for x in (_NO.sub("", p).strip(" .") for p in re.split(r"[,;]", text)) if x)


def negative_prompt(sheet=None, card=None) -> str:
    """Kling's negative prompt: the base list, then the ad's "Never" and the scene's "Avoid"."""
    extra = [
        _as_avoid(s.value) for s in (sheet.never if sheet else None, card.avoid if card else None) if s and s.value
    ]
    return ", ".join([VIDEO_NEGATIVE, *[x for x in extra if x]])[:MAX_PROMPT]


# Spoken words and sounds in a scene's text are for the voice and music, not the silent video AI
# (D32): a quoted line with its lead-in ("voiceover says: "...""), and "audio: ..." / "sound: ...".
_SPOKEN = re.compile(
    r"[^;.\"“]*?\b(?:voice\s*-?\s*over|voice|vo|narrat\w*|whispers?|shouts?|speaks?|says\s*:|said\s*:)[^\"“;]*"
    r"[\"“][^\"”]*[\"”]\.?",
    re.I,
)
_SOUND = re.compile(r"\b(?:audio|sound|sfx|music)\s*:\s*[^;.]*[;.]?", re.I)
_ACCOMPANIED = re.compile(r",?\s*accompanied by (?:a |an |the )?[^;.]*(?:thud|beat|sound|music|bass|hit)\b[^;.]*", re.I)


def film_only(text: str) -> str:
    """The scene's text without what the camera cannot film: spoken lines (they are the voiceover)
    and sound cues. Everything else stays word for word."""
    out = _SOUND.sub("", _ACCOMPANIED.sub("", _SPOKEN.sub("", text)))
    out = re.sub(r"\s*;\s*(?=[;.]|$)", "", out)
    out = re.sub(r"\s*;\s+(?=[A-Z])", ". ", out)  # "hands; She smiles" once the line between is gone
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip(" ;,")


def scene_action(scene: Scene, card) -> tuple[str, bool]:
    """What happens in the scene, and whether it is the user's own words. The user's scene text or
    action goes to Kling word for word (plan A1), unless the writer swapped it (shown, with Undo)."""
    if card.swap is not None and card.swap.value.strip():
        return film_only(card.swap.value.strip()), False
    if card.text.locked:
        return film_only(scene.description.strip() or card.text.value.strip()), True
    if not card.action.empty:
        return film_only(card.action.value.strip()), card.action.locked
    return film_only(scene.description.strip()), False


def _with_subject(action: str, card, sheet) -> str:
    """A guessed action that starts with its verb ("sprints through puddles") gets its person first,
    so the clip says who does it."""
    if not action or not action[0].islower():
        return action
    people = {p.id: p for p in sheet.people}
    for pid in card.who.ids:
        p = people.get(pid)
        if p is not None and pid not in action:
            return f"{pid} ({p.label}) {action}" if p.label else f"{pid} {action}"
    return action


def _clause_cut(text: str, room: int) -> str:
    """Our own text cut to the room at a sentence or clause end (never mid-phrase when it can help)."""
    text = text.strip()
    if len(text) <= room:
        return text
    cut = text[:room]
    ends = [m.start() for m in re.finditer(r"[.;!?,](?=\s)", cut)]
    if ends and ends[-1] > room * 0.5:
        return cut[: ends[-1]].strip()
    return fit_text(text, room)


def _who_part(card, sheet, room: int) -> str:
    """Who is in the shot (only the people in it) and the product: the product kept whole first."""
    people = {p.id: p for p in sheet.people}
    lines = []
    for pid in card.who.ids:
        p = people.get(pid)
        if p is None:
            continue
        bits = [b for b in (p.label, p.look.value.strip(), p.clothes.value.strip()) if b]
        lines.append(f"{p.id}, " + ", ".join(bits))
    product = ""
    if "product" in card.who.ids or not lines:
        product = "Product: " + sheet.product.value.strip().rstrip(".") + "." if not sheet.product.empty else ""
        if not sheet.product_unseen.empty:
            product += " " + sheet.product_unseen.value.strip()
    people_txt = ("In shot: " + "; ".join(lines) + ".") if lines else ""
    if sheet.product.locked and sheet.product.source == "user":
        product_room = max(len(product), 0)  # the user's own product words (no photo, A6): never cut
    else:
        product_room = room - min(len(people_txt), room // 2)
    product = _clip_cut(product, product_room) if product else ""
    people_room = room - len(product) - (1 if product and people_txt else 0)
    people_txt = _clip_cut(people_txt, people_room) if people_room > 20 else ""
    return " ".join(p for p in (people_txt, product) if p)


def _sentence(text: str, *, mine: bool = False) -> str:
    """The text as a sentence that ends cleanly, so the parts join into readable text. The user's
    own words keep their letters: at most a full stop is added."""
    text = text.strip()
    if not text:
        return ""
    if not mine:
        text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?\"”')" else text + "."


def _clip_cut(text: str, room: int) -> str:
    """Our own text cut to the room at a sentence end (or a word), always ending as a sentence."""
    if len(text) <= room:
        return text
    return _sentence(fit_text(text, max(0, room - 1)).rstrip(" ,;:-"), mine=True) if room > 1 else ""


def _place_part(card, sheet, room: int) -> str:
    """Place, light and look, most important first, within the room."""
    place = card.place_change.value.strip() or sheet.place.value.strip()
    bits = [f"Place: {place}" if place else ""]
    bits += [sheet.time_light.value.strip(), sheet.look.value.strip(), sheet.camera_style.value.strip()]
    out = ""
    for b in (_sentence(b) for b in bits if b):
        nxt = f"{out} {b}" if out else b
        if len(nxt) > room:
            return out or _clip_cut(nxt, room)
        out = nxt
    return out


def build_clip(
    scene: Scene,
    card,
    sheet,
    *,
    idx: int,
    count: int,
    style: str,
    notes: str,
    continuous: bool,
    ends_on_next: bool,
    render_s: int,
    has_photo: bool,
    flows_out: bool = True,
) -> ClipText:
    """One clip's text from the slots, with the budget table: the movement, who and the product,
    how it starts and ends, the place and look, the user's notes when there is room, the fixed rules.
    A shot after a cut has no "Starts" or continue line; one before a cut no "Ends" (D32)."""
    flows_in = scene.join == "flow"
    rules = clip_rules(
        style=style, duration_s=render_s, used_s=scene.duration_s, idx=idx, count=count,
        continuous=continuous, ends_on_next=ends_on_next, has_photo=has_photo,
        flows_in=flows_in, flows_out=flows_out,
    )  # fmt: skip
    action, action_mine = scene_action(scene, card)
    if not action_mine:
        action = _with_subject(action, card, sheet)
    # The user's own timeline (A5) comes inside their text; the writer's timeline then stays out.
    timeline = scene.motion_prompt.strip()
    timeline_mine = card.timeline.locked
    timed = bool(TIME_MARK.search(action)) and action_mine
    if timed and not timeline_mine:
        timeline = ""
    # A guessed camera only when nothing else says how the shot moves.
    camera = card.camera.value.strip() if (card.camera.locked or not (timeline or timed)) else ""
    camera = f"Camera: {_sentence(camera)}" if camera else ""
    raw = {"action": len(action), "timeline": len(timeline)}  # the user's own text, as typed
    action, timeline = _sentence(action, mine=True), _sentence(timeline, mine=timeline_mine)

    who = _who_part(card, sheet, WHO_MAX)
    starts = scene.starts.strip() if continuous and idx > 0 and flows_in else ""
    if not starts and card.start.locked:
        starts = card.start.value.strip()
    ends = scene.ends.strip() if continuous and idx < count - 1 and flows_out else ""
    if idx == count - 1 and not card.end.empty:
        ends = card.end.value.strip()  # how the ad ends
    place = _place_part(card, sheet, PLACE_MAX)

    def flow(n: int) -> str:
        return " ".join(
            f"{label}: {_sentence(_clause_cut(t, n - len(label) - 3).rstrip(' ,;:-'), mine=True)}"
            for label, t in (("Starts", starts), ("Ends", ends))
            if t
        )

    flows = flow(FLOW_PART_MAX)
    spare = (WHO_MAX - len(who)) + (2 * FLOW_PART_MAX - len(flows)) + (PLACE_MAX - len(place))
    move_room = min(MOVE_BORROW_MAX, MOVE_MAX + max(0, spare))
    own = [
        t for t, mine in ((action, action_mine), (camera, card.camera.locked), (timeline, timeline_mine)) if t and mine
    ]
    own_len = len(" ".join(own))
    typed = sum(n for k, n in raw.items() if (action_mine if k == "action" else timeline_mine)) + (
        len(camera) if card.camera.locked else 0
    )
    over = max(0, typed - MOVE_BORROW_MAX)
    move_room = max(move_room, min(own_len, MOVE_BORROW_MAX))
    pieces = []
    left = move_room - own_len
    for text, mine in ((action, action_mine), (camera, card.camera.locked), (timeline, timeline_mine)):
        if not text:
            continue
        if mine:
            pieces.append(text)
        elif left > 40:
            cut = _clip_cut(text, left - 1)
            pieces.append(cut)
            left -= len(cut) + 1
    movement = " ".join(pieces)

    def total() -> int:
        return len(" ".join(p for p in (movement, who, flows, place) if p)) + len(rules)

    if total() > TOTAL_MAX:
        flows = flow(FLOW_PART_SHORT)
    if total() > TOTAL_MAX:
        place = _clip_cut(place, max(0, len(place) - (total() - TOTAL_MAX)))
    if total() > TOTAL_MAX:
        who = _clip_cut(who, max(0, len(who) - (total() - TOTAL_MAX)))
    body = " ".join(p for p in (movement, who, flows, place) if p)
    room = TOTAL_MAX - len(body) - len(rules)
    used_notes = "none"
    if notes.strip() and room > 80:
        full = f" Style and world: {notes.strip()}"
        if len(full) <= room:
            body, used_notes = body + full, "full"
        else:
            label = " Style and world (short): " if scene.notes_short.strip() else " Style and world: "
            body += label + fit_text(scene.notes_short.strip() or notes, room - len(label))
            used_notes = "short"
    body = body[: MAX_PROMPT - len(rules)]  # only if the user sends a too-long scene on anyway; the page blocks it
    text = body + rules
    parts = [
        ClipPart("movement", len(movement), move_room),
        ClipPart("who", len(who), WHO_MAX),
        ClipPart("start_end", len(flows), 2 * FLOW_PART_MAX),
        ClipPart("place", len(place), PLACE_MAX),
        ClipPart("rules", len(rules), RULES_MAX),
    ]
    if used_notes != "none":
        parts.insert(4, ClipPart("notes", len(body) - len(" ".join(p for p in (movement, who, flows, place) if p)),
                                 max(0, room)))  # fmt: skip
    field_name = "motion_prompt" if timeline_mine and len(timeline) >= len(action) else "description"
    if not action_mine:
        field_name = "motion_prompt"
    return ClipText(
        text=text,
        chars=len(text),
        too_long_by=over,
        notes=used_notes,
        parts=parts,
        negative=negative_prompt(sheet, card),
        shorten_field=field_name,
    )


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
    card=None,
    sheet=None,
    flows_out: bool = True,
) -> ClipText:
    """The exact text Kling gets for this scene (at most 2,500 characters). `render_s` is the clip
    the model makes (5 or 10 s; by default the one the scene's length needs). With the structure
    (`sheet`, and the scene's `card` when it has one) it is built from the slots (phase 4);
    without it, as before (an older storyboard, or the slot filler failed)."""
    duration_s = render_s or render_seconds(scene.duration_s)
    if sheet is not None:
        if card is None:
            from .ad_structure import SceneCard  # a scene added on the page: its own text, the shared sheet

            card = SceneCard()
        return build_clip(
            scene, card, sheet, idx=idx, count=count, style=style, notes=notes, continuous=continuous,
            ends_on_next=ends_on_next, render_s=duration_s, has_photo=has_photo, flows_out=flows_out,
        )  # fmt: skip
    rules = clip_rules(
        style=style,
        duration_s=duration_s,
        used_s=scene.duration_s,
        idx=idx,
        count=count,
        continuous=continuous,
        ends_on_next=ends_on_next,
        has_photo=has_photo,
        flows_in=scene.join == "flow",
        flows_out=flows_out,
    )
    own = scene_text(scene)
    over = max(0, len(own) + len(rules) - MAX_PROMPT)
    body = own[: MAX_PROMPT - len(rules)]  # cut only if the user sends it on anyway; the page blocks it first
    room = MAX_PROMPT - len(rules) - len(body)
    if continuous:
        for label, text, show in (
            ("Starts", scene.starts, idx > 0 and scene.join == "flow"),
            ("Ends", scene.ends, idx < count - 1 and flows_out),
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
    card=None,
    sheet=None,
    flows_out: bool = True,
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
        card=card,
        sheet=sheet,
        flows_out=flows_out,
    )
    arguments = {"prompt": prompt.text, "duration": str(duration_s), "negative_prompt": prompt.negative}
    settings: dict = {"duration": duration_s}
    if end_image is not None:
        settings["tail_image_sha256"] = end_image_sha256
    if prompt.negative != VIDEO_NEGATIVE:
        settings["negative_prompt"] = prompt.negative
    key = cache_key(model=model, prompt=prompt.text, seed=None, input_sha256=reference_sha256, settings=settings)
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
