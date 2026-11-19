"""Media cache key: every generation is stored under model + prompt + seed + input image
hash + settings, so evals, replays and the gallery never pay twice for the same render."""

from __future__ import annotations

import hashlib
import json


def cache_key(*, model: str, prompt: str, seed: int | None, input_sha256: str, settings: dict) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "seed": seed,
        "input": input_sha256,
        "settings": settings,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
