"""Reference image per scene: the real product photo edited into the scene (Nano Banana edit on fal).

The image is generated at the master aspect ratio, because the image-to-video model
takes the clip's ratio from its input image.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Scene
from .llm_trace import Usage
from .media_cache import cache_key
from .providers.media import InputImage, MediaRequest
from .styles import IMAGE as IMAGE_STYLE

FIDELITY = (
    " Keep the product from the reference photo exactly the same: same shape, proportions, colours, logo"
    " and packaging text. Add no other text, letters, signs or captions anywhere in the image."
)


# An own picture whose shape is too far from the ad's (a crop would cut more than a quarter) is
# placed on a soft blurred copy of itself, then the image model replaces the blurred areas with
# more of the same scene, so the clip starts from one full-frame photo. A blurred fill on its own
# was animated by Kling into every scene that followed (the owner's real test, 21 Nov 2026).
EXTEND = (
    "This photo was placed in a frame of a different shape; the soft blurred areas at its edges are"
    " only a placeholder. Replace every blurred area with a natural, sharp continuation of the same"
    " scene, so the whole frame is one seamless photo. Keep the sharp part exactly as it is: the same"
    " people, product, place, light, colours, position and framing. No borders, bars, frames or blur,"
    " and no added text, letters, signs or captions."
)


@dataclass
class PlannedRender:
    request: MediaRequest
    cache_key: str
    usage: Usage  # billing units of this render, for the estimate and the record


def plan_scene_image(
    *,
    model: str,
    scene: Scene,
    aspect_ratio: str,
    seed: int,
    product: InputImage,
    product_sha256: str,
    style: str = "realistic",
    notes: str = "",
    keep_same: str | None = None,
    cast: str = "",
    people: list[tuple[str, InputImage, str]] = (),
) -> PlannedRender:
    """`keep_same` is set in a continuous shot (D30): then the picture is also the scene's first moment
    as the continuity check wrote it, with what stays the same in every scene. A shot after a cut
    (D32) opens on its own picture, so it never gets the shot before's moment (that made collages).

    `cast` is how the people in this shot look, from the cast sheet; `people` is (name, picture,
    sha256) of each one's first picture, sent as more reference photos so the same person comes back
    in every shot (strategy plan A4; the owner's hoodie test, 27 Nov 2026: a new face in every shot)."""
    prompt = scene.image_prompt.strip() or scene.description.strip()
    if cast.strip():
        prompt += " People in this shot: " + cast.strip()
    for n, (name, _, _) in enumerate(people, start=2):
        prompt += (
            f" Reference photo {n} shows {name}: keep exactly the same person (face, skin tone, hair, age and build)."
            " Take only the person from it, never its place, pose, light or framing."
        )
    if keep_same is not None:
        if scene.starts.strip() and scene.join == "flow":
            prompt += " First moment of the shot: " + scene.starts.strip()
        if keep_same.strip():
            prompt += " Same in every scene: " + keep_same.strip()
    if notes.strip():
        prompt += " Style and world for the whole ad: " + notes.strip()
    prompt += FIDELITY + " " + IMAGE_STYLE.get(style, IMAGE_STYLE["realistic"])
    arguments = {
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": aspect_ratio,
        "output_format": "jpeg",
        "seed": seed,
    }
    settings = {"aspect_ratio": aspect_ratio, "output_format": "jpeg", "num_images": 1}
    if people:
        settings["people"] = [sha for _, _, sha in people]
    key = cache_key(model=model, prompt=prompt, seed=seed, input_sha256=product_sha256, settings=settings)
    return PlannedRender(
        request=MediaRequest(
            kind="image",
            model=model,
            arguments=arguments,
            input_image=product,
            image_field="image_urls",
            extra_images=[img for _, img, _ in people],
        ),
        cache_key=key,
        usage=Usage(images=1),
    )


def cast_line(card, sheet) -> str:
    """How the people in a shot look, from the cast sheet: "P1 (the creator): <look>; wears <clothes>"."""
    if card is None or sheet is None:
        return ""
    by_id = {p.id: p for p in sheet.people}
    lines = []
    for pid in card.who.ids:
        p = by_id.get(pid)
        if p is None:
            continue
        bits = [
            x
            for x in (p.look.value.strip(), f"wears {p.clothes.value.strip()}" if p.clothes.value.strip() else "")
            if x
        ]
        lines.append(
            f"{pid} ({p.label or 'a person'}): " + "; ".join(bits) if bits else f"{pid} ({p.label or 'a person'})"
        )
    return ". ".join(lines)


def plan_extend_image(
    *, model: str, aspect_ratio: str, seed: int, placed: InputImage, placed_sha256: str
) -> PlannedRender:
    """Extend an own picture (already placed on its blurred copy at the ad's shape) to the full frame."""
    arguments = {
        "prompt": EXTEND,
        "num_images": 1,
        "aspect_ratio": aspect_ratio,
        "output_format": "jpeg",
        "seed": seed,
    }
    key = cache_key(
        model=model,
        prompt=EXTEND,
        seed=seed,
        input_sha256=placed_sha256,
        settings={"aspect_ratio": aspect_ratio, "output_format": "jpeg", "num_images": 1},
    )
    return PlannedRender(
        request=MediaRequest(
            kind="image", model=model, arguments=arguments, input_image=placed, image_field="image_urls"
        ),
        cache_key=key,
        usage=Usage(images=1),
    )
