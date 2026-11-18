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


def plan_scene_video(
    *, model: str, scene: Scene, duration_s: int, reference: InputImage, reference_sha256: str
) -> PlannedRender:
    if duration_s not in (5, 10):
        raise ValueError("Kling image-to-video accepts 5 or 10 seconds")
    prompt = scene.motion_prompt.strip() + " Keep the product unchanged; realistic handheld phone footage."
    arguments = {"prompt": prompt, "duration": str(duration_s)}
    key = cache_key(
        model=model,
        prompt=prompt,
        seed=None,
        input_sha256=reference_sha256,
        settings={"duration": duration_s},
    )
    return PlannedRender(
        request=MediaRequest(
            kind="video", model=model, arguments=arguments, input_image=reference, image_field="image_url"
        ),
        cache_key=key,
        usage=Usage(seconds=duration_s),
    )
