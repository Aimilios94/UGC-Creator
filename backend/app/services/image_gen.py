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

FIDELITY = (
    " Keep the product from the reference photo exactly the same: same shape, proportions, colours, logo"
    " and packaging text, with no extra text added. Realistic smartphone photo, natural light."
)


@dataclass
class PlannedRender:
    request: MediaRequest
    cache_key: str
    usage: Usage  # billing units of this render, for the estimate and the record


def plan_scene_image(
    *, model: str, scene: Scene, aspect_ratio: str, seed: int, product: InputImage, product_sha256: str
) -> PlannedRender:
    prompt = scene.image_prompt.strip() + FIDELITY
    arguments = {
        "prompt": prompt,
        "num_images": 1,
        "aspect_ratio": aspect_ratio,
        "output_format": "jpeg",
        "seed": seed,
    }
    key = cache_key(
        model=model,
        prompt=prompt,
        seed=seed,
        input_sha256=product_sha256,
        settings={"aspect_ratio": aspect_ratio, "output_format": "jpeg", "num_images": 1},
    )
    return PlannedRender(
        request=MediaRequest(
            kind="image", model=model, arguments=arguments, input_image=product, image_field="image_urls"
        ),
        cache_key=key,
        usage=Usage(images=1),
    )
