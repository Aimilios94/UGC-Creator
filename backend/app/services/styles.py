"""Visual styles: what each one adds to the image and video prompts. DB-free.

From a real product photo the edit model keeps the product most faithfully in the realistic
and cinematic styles; the 3D and 2D styles restyle the whole scene, product included
(feedback round 2: an edit model tends to keep the style of its input).
"""

from __future__ import annotations

IMAGE = {
    "realistic": "Realistic smartphone photo with an authentic UGC look, natural light.",
    "cinematic": "Cinematic photograph: shallow depth of field, motivated dramatic lighting, rich film colour grade.",
    "3d": "Stylised 3D render (CGI): soft global illumination, clean physically based materials.",
    "2d": "2D illustration in an anime style: clean line art, flat cel shading, bold readable shapes.",
}

VIDEO = {
    "realistic": "Realistic handheld phone footage, natural motion and light.",
    "cinematic": "Cinematic camera work: smooth stabilised moves, film-like colour grade.",
    "3d": "3D animation with smooth CG motion; keep the 3D look in every frame.",
    "2d": "2D anime-style animation; keep the line art and flat shading consistent in every frame.",
}

LABELS = {
    "realistic": "realistic smartphone UGC video",
    "cinematic": "cinematic, film-like live action",
    "3d": "stylised 3D animation (CGI)",
    "2d": "2D illustration / anime-style animation",
}

# Kling's negative prompt: no lettering (models write made-up text), no warping.
VIDEO_NEGATIVE = (
    "text, letters, words, captions, subtitles, watermark, logo overlay, blur, distortion, warping, low quality"
)
