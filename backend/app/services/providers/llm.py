"""Text and vision LLM behind Pydantic AI: openai | anthropic | mock.

The mock provider is a Pydantic AI FunctionModel that returns deterministic, schema-valid
outputs built from the brief in the prompt, so the whole flow runs offline in tests and CI.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ...config import Settings
from ...errors import ProviderNotConfigured

BRIEF_RE = re.compile(r"<brief>(.*?)</brief>", re.S)
STORY_RE = re.compile(r"<story>(.*?)</story>", re.S)
SCENES_RE = re.compile(r"<scenes>(.*?)</scenes>", re.S)
NOTES_RE = re.compile(r"<notes>(.*?)</notes>", re.S)
TEXT_RE = re.compile(r"<text>(.*?)</text>", re.S)
BEATS_RE = re.compile(r"<beats>(.*?)</beats>", re.S)
PARAGRAPHS_RE = re.compile(r"<paragraphs>(.*?)</paragraphs>", re.S)
TARGET_RE = re.compile(r"at most (\d+) characters")
COUNT_RE = re.compile(r"write exactly (\d+) scene", re.I)
ADD_RE = re.compile(r"<add>(.*?)</add>", re.S)
SHEET_RE = re.compile(r"<sheet>(.*?)</sheet>", re.S)
TIMED_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:-|–|to)\s*\d+(?:[.,]\d+)?\s*s\b|\b\d{1,2}:\d{2}\b", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"”])\s+")  # a sentence may end inside quotes


@dataclass
class LlmHandle:
    model: Model
    provider: str  # openai | anthropic | mock
    model_name: str  # priced via llm_trace.PRICES
    settings: dict


def _texts(messages):
    for m in messages:
        for part in getattr(m, "parts", []):
            content = getattr(part, "content", None)
            for t in content if isinstance(content, list) else [content]:
                if isinstance(t, str):
                    yield t


def _brief_from(messages) -> dict:
    """The brief (and the user's story, if any) from the prompt, for the mock outputs."""
    brief: dict = {}
    for t in _texts(messages):
        if not brief and (match := BRIEF_RE.search(t)):
            try:
                brief = json.loads(match.group(1))
            except json.JSONDecodeError:
                brief = {}
        if match := STORY_RE.search(t):
            try:
                brief["story"] = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        for key, rx in (
            ("_scenes", SCENES_RE),
            ("_notes", NOTES_RE),
            ("_text", TEXT_RE),
            ("_beats", BEATS_RE),
            ("_paragraphs", PARAGRAPHS_RE),
            ("_add", ADD_RE),
            ("_sheet", SHEET_RE),
        ):
            if match := rx.search(t):
                try:
                    brief[key] = json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
        if match := TARGET_RE.search(t):
            brief["_target"] = int(match.group(1))
        if match := COUNT_RE.search(t):
            brief["_count"] = int(match.group(1))
    return brief


def mock_analysis(brief: dict) -> dict:
    name = brief.get("product_name", "the product")
    return {
        "product_type": f"{name} (mock analysis)",
        "visual_description": f"{name}: product as shown in the uploaded photo, same shape, colours and label.",
        "packaging_text": [name],
        "key_features": ["as described in the brief"],
        "people_in_photo": False,
    }


def _story_parts(story: str) -> list[str] | None:
    """The story's parts, in order (mock only): its timed beats when it has them."""
    from ..scene_splitter import story_beats

    beats = story_beats(story)
    if beats:
        return [b.text for b in beats]
    return _sentence_parts(story)


def _sentence_parts(story: str) -> list[str] | None:
    """The story in three parts, in order (mock only): by its timestamped beats if it has them, else by sentences."""
    text = story.strip()
    if not text:
        return None
    beats = [b.strip() for b in re.split(r"\n\s*\n|(?=\b\d{1,2}:\d{2}\s*[-\u2013]\s*\d{1,2}:\d{2})", text) if b.strip()]
    timed = re.compile(r"^\d{1,2}:\d{2}")
    if len(beats) > 1 and not timed.match(beats[0]) and timed.match(beats[1]):
        beats = [beats[0] + " " + beats[1], *beats[2:]]  # a heading before the first timestamp joins it
    if len(beats) < 3:
        beats = [x.strip() for x in SENTENCE_END.split(text) if x.strip()]
    if timed.match(beats[0]) or any(timed.match(b) for b in beats[1:]):
        n = min(len(beats), 5)  # a timed story: one scene per beat (1-5), as the real writer is told
    else:
        n = 3
        if len(beats) < 3:
            beats = (beats * 3)[:3]
    return [" ".join(beats[i * len(beats) // n : (i + 1) * len(beats) // n]) for i in range(n)]


def _seconds(part: str) -> int | None:
    """A story part's length from its timestamps, for example "0:02 - 0:06" -> 4 (mock only)."""
    stamps = [int(m) * 60 + int(sec) for m, sec in re.findall(r"(\d{1,2}):(\d{2})", part)]
    if len(stamps) < 2:
        return None
    return max(2, min(10, max(stamps) - min(stamps)))


def _spoken(part: str) -> str:
    """Quoted text in a story part is its spoken line (mock only)."""
    quotes = re.findall(r"[\"\u201c]([^\"\u201d]{3,200})[\"\u201d]", part)
    return " ".join(quotes)[:220]


def mock_storyboard(brief: dict) -> dict:
    """A detailed, schema-valid storyboard built from the brief, as the real model is asked to write."""
    name = brief.get("product_name", "the product")
    offer = brief.get("offer") or ""
    keep = f"Keep {name} exactly as in the reference photo: same shape, colours, logo and packaging text."
    parts = brief.get("_beats") or _story_parts(brief.get("story") or "")
    lines = [
        f"Stop scrolling: this is {name}.",
        "Here is how it works, in one step.",
        f"Get yours today. {offer}".strip(),
    ]
    scenes = [
        {
            "role": "hook",
            "description": f"Close-up of {name} on a bright kitchen counter, filmed like a phone video.",
            "image_prompt": (
                f"A close-up of {name} standing upright on a light oak kitchen counter, slightly left of centre, "
                "with a ceramic mug and a folded linen towel softly out of focus behind it. Morning in a small "
                "city apartment. Medium close-up from chest height, a 26 mm phone lens, slight downward angle, "
                "the product filling about a third of the frame. Soft window light from the left, warm 4,500 K, "
                "gentle shadows to the right. Palette of cream, oak and soft green; calm, fresh mood. " + keep
            ),
            "motion_prompt": (
                "0-1 s: the phone camera holds on the product with a slight natural handheld sway, sunlight "
                "flickering softly through the window. 1-3 s: a slow push-in toward the product, about 20 percent "
                "closer, focus staying on the logo while the mug behind blurs further. 3-5 s: the camera eases "
                "to a stop, a hand enters from the right and rests next to the product; final frame is a tight, "
                "well-lit close-up of the product, ready to cut to the demo."
            ),
            "on_screen_text": f"Meet {name}"[:80],
        },
        {
            "role": "demo",
            "description": f"Hands showing {name} in use at home.",
            "image_prompt": (
                f"Two hands holding {name} at chest height in a cosy living room, the product turned three "
                "quarters toward the camera. A sofa with a knitted throw and a plant in the soft background. "
                "Medium shot, eye level, 26 mm phone lens, product centred. Soft daylight from a large window "
                "behind the camera, slight warm fill from a lamp. Palette of warm neutrals with one green accent; "
                "relaxed, practical mood. " + keep
            ),
            "motion_prompt": (
                "0-1 s: static handheld framing on the hands and product. 1-3 s: the hands slowly turn the "
                "product to show its front, then its side, while the camera follows with a gentle pan of a few "
                "degrees. 3-4 s: a short tilt down as the hands demonstrate the main feature, focus following "
                "the product. 4-5 s: the hands bring the product back to face the camera and pause; final frame "
                "shows the front of the product clearly, centred."
            ),
            "on_screen_text": "How it works",
        },
        {
            "role": "cta",
            "description": f"{name} centred on a clean background with space for the call to action.",
            "image_prompt": (
                f"{name} centred on a clean, softly lit seamless background in a pale warm grey, a subtle shadow "
                "under the product. Product shot, straight on at product height, 50 mm lens look, the product "
                "filling half the frame with empty space above and below for text added later. Large soft key "
                "light from the upper left, a faint rim light from behind. Palette of warm grey and the "
                "product's own colours; confident, premium mood. " + keep
            ),
            "motion_prompt": (
                "0-2 s: a slow, smooth orbit of about 15 degrees around the product from left to right, the "
                "product staying centred and sharp. 2-4 s: the camera settles and makes a gentle push-in, the "
                "rim light adding a soft glint on the product's edge. 4-5 s: hold still on a clean, centred "
                "frame with empty space above the product for the call to action."
            ),
            "on_screen_text": offer[:80],
        },
    ]
    if not parts and (brief.get("_count") or brief.get("video_length_s")):
        # The scene count set in code (scene_plan.py, the slot filler): repeat the middle scene as needed.
        from ..scene_plan import scenes_for_length

        n = brief.get("_count") or scenes_for_length(int(brief["video_length_s"]), 2.0)
        middle = scenes[1]
        scenes = [scenes[2]] if n == 1 else [scenes[0], *[dict(middle) for _ in range(n - 2)], scenes[2]]
        lines = [lines[2]] if n == 1 else [lines[0], *([lines[1]] * (n - 2)), lines[2]]
    hooks = [
        {"formula": "pov", "text": f"POV: you finally found {name}"},
        {"formula": "problem_first", "text": f"Tired of the old way? Try {name}"},
        {"formula": "three_reasons", "text": f"3 reasons people pick {name}"},
    ]
    if parts:
        # The user's story leads: one scene per part, its spoken lines kept, the hooks open it.
        template = scenes
        scenes = [dict(template[0 if i == 0 else (2 if i == len(parts) - 1 else 1)]) for i in range(len(parts))]
        for scene, part in zip(scenes, parts, strict=True):
            # Like the real writer: a short summary, a still first frame, and the timed movement.
            plain = re.sub(r"^.*?\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\s*(\([^)]*\))?:?\s*", "", part).strip() or part
            first = SENTENCE_END.split(plain)[0]
            scene["description"] = part  # the story's own text for this scene
            scene["image_prompt"] = f"Still first frame of this scene, before anything moves: {first} {keep}"
            scene["motion_prompt"] = part
            scene["voiceover"] = _spoken(part)
            # Ideas to pick from, like the real writer (owner, 22 Nov 2026: the fields start empty).
            scene["voiceover_ideas"] = [f"Meet {name}.", f"{name}, made for moments like this."]
            scene["text_ideas"] = [f"Meet {name}"[:80], name[:80]]
            scene["duration_s"] = _seconds(part) or 5
        # Short opening lines a viewer would hear (the real writer bases them on the story).
        hooks = [
            {"formula": "pov", "text": f"POV: you just found {name}"[:160]},
            {"formula": "problem_first", "text": f"Most people scroll past. Not when {name} walks by."[:160]},
            {"formula": "three_reasons", "text": f"3 reasons people turn around when they see {name}"[:160]},
        ]
    else:
        for scene, line in zip(scenes, lines, strict=True):
            scene["voiceover"] = line
    swaps, fixes = [], []
    if sheet := brief.get("_sheet"):
        # Like the real writer with a sheet (phase 4): the movement is only a timeline for the
        # scene's own action (none when the user's text has its times), and a user action that
        # Kling renders badly is swapped, with a reason.
        cards = sheet.get("scenes") or []
        for i, scene in enumerate(scenes):
            own = scene["description"] if parts else ""
            scene["motion_prompt"] = "" if TIMED_RE.search(own) else _mock_timeline(scene.get("duration_s", 5))
            card = cards[i] if i < len(cards) else {}
            action = card.get("action") or ""
            if card.get("action_is_users") and re.search(r"\bthrow", action, re.I):
                safe = re.sub(r"\bthrows\b", "holds out", action)
                safe = re.sub(r"\bthrow\b", "hold out", safe)
                swaps.append({"scene": i + 1, "action": safe.rstrip(".") + "; the crowd stays still behind them.",
                              "reason": "Kling renders throws and catches badly"})  # fmt: skip
        # A guessed light that contradicts an answer is corrected (phase 5), like the real writer.
        answered = " ".join((sheet.get("answers") or {}).values()).lower()
        if "night" in answered and "time_light" in (sheet.get("guessed") or []) and "night" not in sheet["time_light"]:
            fixes.append({"slot": "time_light", "value": "night, street lamps and neon light"})
    return {"title": name, "scenes": scenes, "hooks": hooks, "cta_text": "Shop now", "swaps": swaps,
            "sheet_fixes": fixes}  # fmt: skip


def _mock_timeline(seconds: int) -> str:
    """A short timeline for the scene's own action (mock only)."""
    end = int(seconds or 5)
    mid = max(1, end // 2)
    return (
        f"0-{mid} s: the camera moves in slowly as the action starts. "
        f"{mid}-{end} s: it holds steady as the moment ends."
    )


_BEAT_RE = re.compile(r"\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s*s:")


def _last_beat(movement: str) -> str:
    """The last timed beat of a shot list, or its last sentence (mock only)."""
    beats = [b.strip(" .") for b in _BEAT_RE.split(movement or "") if b.strip(" .")]
    if beats:
        return beats[-1][:300]
    sentences = [s for s in SENTENCE_END.split((movement or "").strip()) if s.strip()]
    return (sentences[-1] if sentences else "the camera keeps its slow move")[:300]


def _first_sentences(text: str, room: int) -> str:
    """The text's first sentences that fit in `room` characters (mock only)."""
    out = ""
    for sentence in SENTENCE_END.split((text or "").strip()):
        if len(out) + len(sentence) + 1 > room:
            break
        out = f"{out} {sentence}".strip()
    return out


def mock_continuity(brief: dict) -> dict:
    """How each scene starts and ends, so the cuts match, as the real checker is asked (mock only)."""
    scenes = brief.get("_scenes") or [{}]
    notes = brief.get("_notes") or ""
    flows = []
    for i, sc in enumerate(scenes):
        end = _last_beat(sc.get("movement", ""))
        if i == 0:
            starts = "The first picture, the camera already easing into a slow push-in at chest height."
        else:
            starts = f"Exactly the last moment of scene {i}: {flows[-1]['_end']}; the same move carries on."
        ends = end if i == len(scenes) - 1 else f"{end}; the camera keeps moving at the same speed into scene {i + 2}."
        room = int(sc.get("notes_room") or 0)
        short = _first_sentences(notes, room) if notes and room < len(notes) else ""
        flows.append({"starts": starts[:800], "ends": ends[:800], "notes_short": short, "_end": end})
    return {
        "keep_same": "Same camera height and lens feel, the same people and clothes, the same place, light and "
        "colours as in scene 1, unless the story changes them.",
        "scenes": [{k: f[k] for k in ("starts", "ends", "notes_short")} for f in flows],
    }


def mock_shorten(brief: dict) -> dict:
    """A scene's movement shortened to the target, whole sentences kept in order (mock only)."""
    text = brief.get("_text") or ""
    target = int(brief.get("_target") or len(text))
    return {"text": _first_sentences(text, target) or text[:target]}


_NOTE_PARA = re.compile(r"^[\w ]{2,24}:")  # "Style: ...", "Light and colour: ..." (mock only)
_PERSON = re.compile(r"\b(guy|man|woman|girl|boy|he|she|person|friend|creator)\b", re.I)


def _first_sentence(text: str) -> str:
    return (SENTENCE_END.split(text.strip())[0] if text.strip() else "").strip()[:300]


_PLACE = re.compile(
    r"\b(?:in|at|on|near|through|outside|inside|across)\s+((?:the\s+|a\s+)?[A-Za-zÀ-ÿ][\w'-]*(?:\s+[A-Za-zÀ-ÿ][\w'-]*){0,2})",
    re.I,
)
_NOT_PLACE = frozenset(
    "rain snow sun sunlight morning evening night day dark light slow motion hand hands frame shot focus time "
    "front back background style camera close my his her their its one two".split()
)
_TIME = re.compile(r"\b(dawn|sunrise|morning|noon|afternoon|sunset|golden hour|dusk|evening|night|midnight)\b", re.I)
_WEATHER = re.compile(r"\b(rain|raining|rainy|snow|snowing|fog|foggy|storm|sunny|cloudy)\b", re.I)


def _mock_place(story: str) -> dict:
    """A place the story names, word for word (mock only); else a guess that fits its weather."""
    for m in _PLACE.finditer(story):
        words = m.group(1).split()
        head = words[1] if words[0].lower() in ("the", "a") and len(words) > 1 else words[0]
        if head.lower() not in _NOT_PLACE:
            return {"value": m.group(1), "from_user": True}
    if _WEATHER.search(story):
        return {"value": "a city street outdoors"}
    return {"value": "a bright, tidy room at home"}


def _mock_time(story: str) -> dict:
    """The time and weather the story names, as a reworded value (mock only); else a daylight guess."""
    said = [m.group(0).lower() for rx in (_TIME, _WEATHER) for m in rx.finditer(story)]
    if said:
        return {"value": ", ".join(dict.fromkeys(said)) + ", natural light", "from_story": True}
    return {"value": "daytime, soft window light"}


def _mock_label(story: str) -> str:
    """The person as the story calls them ("the girl"), else "the person" (mock only)."""
    m = _PERSON.search(story)
    return f"the {m.group(1).lower()}" if m and m.group(1).lower() not in ("he", "she") else "the person"


def mock_slots(brief: dict) -> dict:
    """The slot filler (mock only): paragraphs with a label ("Style: ...") are notes, the others one
    scene each; the cast and world are plain guesses; each scene's first sentence is the user's action."""
    name = brief.get("product_name", "the product")
    story = brief.get("story") or ""
    uses, texts = [], []
    if paras := brief.get("_paragraphs"):
        for p in paras:
            if _NOTE_PARA.match(p["text"]) or len(texts) >= 5:
                uses.append({"paragraph": p["paragraph"], "use": "notes"})
            else:
                texts.append(p["text"])
                uses.append({"paragraph": p["paragraph"], "use": "scene", "scene": len(texts)})
    elif scenes := brief.get("_scenes"):
        texts = [s.get("text", "") for s in scenes]
    else:
        texts = [""] * int(brief.get("_count") or 3)
        if story.strip():
            texts[0] = story.strip()  # a story with no shape: its words are the first scene's action
    person = bool(_PERSON.search(story))
    people = (
        [{"id": "P1", "label": _mock_label(story), "look": {"value": "late 20s, short dark hair, relaxed smile"},
          "clothes": {"value": f"wears {name}"}}]
        if person else []
    )  # fmt: skip
    who = ["P1", "product"] if person else ["product"]
    cards = []
    for i, text in enumerate(texts):
        first = _first_sentence(text)
        cards.append(
            {
                "who": who,
                "action": {"value": first, "from_user": True} if first else {"value": f"shows {name} to the camera"},
                "camera": {"value": "handheld phone, slow push in"},
                "product_moment": {"value": "worn" if person else "held up to the camera"},
                "end": {"value": "the camera settles on the product"} if i == len(texts) - 1 else {"value": ""},
            }
        )
    short = 0 < len(story.split()) < 12  # a short, vague story; with no story the brief leads
    questions = (
        [
            {"slot": "who", "text": "Who is in your ad?", "options": ["A young man", "A young woman", "Only hands"]},
            {"slot": "place", "text": "Where does it happen?", "options": ["A city street", "At home", "Outdoors"]},
        ]
        if short
        else []
    )
    return {
        "paragraphs": uses,
        "sheet": {
            "people": people,
            "place": _mock_place(story),
            "time_light": _mock_time(story),
            "look": {"value": "realistic phone video"},
            "camera_style": {"value": "handheld phone, UGC feel"},
            "never": {"value": "no text, no other brands"},
        },
        "scenes": cards,
        "questions": questions,
    }


def mock_add_scenes(brief: dict) -> dict:
    """New scenes for "Add scenes to reach N s" (mock only): demo scenes before the last one."""
    ask = brief.get("_add") or {}
    count, after = int(ask.get("count") or 1), int(ask.get("after") or 1)
    name = brief.get("product_name", "the product")
    scene = {
        "role": "demo",
        "description": f"A closer look at {name} in use.",
        "image_prompt": f"Still first frame: a close, well-lit shot of {name} in use.",
        "motion_prompt": "0-2 s: slow push in on the product. 2-5 s: the camera eases to a stop on its details.",
        "voiceover": "",
        "on_screen_text": "",
        "duration_s": 5,
    }
    return {"scenes": [{"after": after, "scene": scene} for _ in range(count)]}


MOCK_TASKS: dict[str, Callable[[dict], dict]] = {
    "analyze": mock_analysis,
    "slots": mock_slots,
    "storyboard": mock_storyboard,
    "add_scenes": mock_add_scenes,
    "continuity": mock_continuity,
    "shorten": mock_shorten,
}


def _mock_model(task: str) -> FunctionModel:
    builder = MOCK_TASKS[task]

    def respond(messages, info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool_name=tool, args=builder(_brief_from(messages)))])

    return FunctionModel(respond, model_name=f"mock-{task}")


def build_llm(settings: Settings, task: str) -> LlmHandle:
    provider = settings.llm_provider
    if provider == "mock":
        return LlmHandle(model=_mock_model(task), provider="mock", model_name="mock", settings={})
    if provider == "openai":
        if not settings.openai_api_key:
            raise ProviderNotConfigured("OPENAI_API_KEY is not set")
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        model = OpenAIChatModel(settings.llm_model, provider=OpenAIProvider(api_key=settings.openai_api_key))
        model_settings: dict[str, Any] = {"max_tokens": settings.llm_max_output_tokens}
        if settings.llm_model.startswith(("gpt-5", "o")):
            model_settings["openai_reasoning_effort"] = "low"
        return LlmHandle(model=model, provider="openai", model_name=settings.llm_model, settings=model_settings)
    if provider == "anthropic":
        if not (settings.anthropic_api_key and settings.anthropic_model):
            raise ProviderNotConfigured("ANTHROPIC_API_KEY and ANTHROPIC_MODEL are required (M4)")
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        model = AnthropicModel(settings.anthropic_model, provider=AnthropicProvider(api_key=settings.anthropic_api_key))
        return LlmHandle(
            model=model,
            provider="anthropic",
            model_name=settings.anthropic_model,
            settings={"max_tokens": settings.llm_max_output_tokens},
        )
    raise ProviderNotConfigured(f"unknown LLM_PROVIDER {provider!r}")
