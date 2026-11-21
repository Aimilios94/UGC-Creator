"""Image-to-video per scene from the approved reference image (Kling on fal), async submit and poll.

The clip's aspect ratio comes from the reference image. The model's own audio is not
used: the voiceover and music are added in compose (M2).
"""

from __future__ import annotations

from ..models import Scene
from .image_gen import PlannedRender
from .llm_trace import Usage
from .media_cache import cache_key
from .providers.media import InputImage, MediaRequest
from .styles import VIDEO as VIDEO_STYLE
from .styles import VIDEO_NEGATIVE

MAX_PROMPT = 2500  # Kling's prompt limit (fal OpenAPI schema, checked 20 Nov 2026)


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
) -> PlannedRender:
    """One clip. In a continuous shot (D30) the clip also gets how it starts and ends (from the
    continuity check) and what stays the same; when the next scene has its own picture, the clip
    ends on that picture (`end_image`), and compose plays the whole clip in the scene's time."""
    if duration_s not in (5, 10):
        raise ValueError("Kling image-to-video accepts 5 or 10 seconds")
    used = min(used_s or duration_s, duration_s)
    tail = " One continuous take, no cuts. Keep the product unchanged in every frame. "
    tail += VIDEO_STYLE.get(style, VIDEO_STYLE["realistic"])
    if end_image is not None:
        tail += (
            " The last frame is the end image given: move steadily toward it through the whole clip, so the"
            " clip lands on it exactly; it is the first frame of the next scene."
        )
        if used < duration_s:
            tail += (
                f" The clip is played {duration_s / used:.2g} times faster (in {used} seconds):"
                " keep every movement slow and smooth."
            )
    elif used < duration_s:
        tail += f" Only the first {used} seconds are used: play all the beats within them, then hold the last frame."
    elif duration_s == 10:
        tail += " The clip is 10 seconds: spread these beats evenly over the 10 seconds."
    idx, count = position
    if count > 1:
        # The same rule for every clip, so the scenes join smoothly (D29).
        if idx > 0:
            tail += (
                " This shot continues the previous scene: start with the camera already moving in the same"
                " direction and at the same speed, no restart, no new camera position."
            )
        if idx < count - 1:
            tail += " End mid-movement, so the next scene can carry the same camera move on."
        if continuous and idx > 0:
            tail += " The first frame is the last frame of the previous scene."
    motion = (scene.motion_prompt.strip() or scene.description.strip())[: MAX_PROMPT - len(tail)]
    # Then, while there is room: how the shot starts and ends, what stays the same, the style notes.
    extras = []
    if continuous:
        if idx > 0 and scene.starts.strip():
            extras.append(f" Starts: {scene.starts.strip()}")
        if idx < count - 1 and scene.ends.strip():
            extras.append(f" Ends: {scene.ends.strip()}")
        if keep_same.strip():
            extras.append(f" Same in every scene: {keep_same.strip()}")
    if notes.strip():
        extras.append(f" Style and world: {notes.strip()}")
    room = MAX_PROMPT - len(tail) - len(motion)
    body = motion
    for extra in extras:
        if room <= 80:
            break
        body += extra[:room]
        room -= len(extra[:room])
    prompt = body + tail
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
