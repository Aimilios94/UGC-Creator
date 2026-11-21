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

VIDEO = {  # short (strategy plan A2, D31): part of the clip's fixed rules, 300 characters at most
    "realistic": "Realistic phone footage, natural light.",
    "cinematic": "Cinematic, smooth stabilised moves, film grade.",
    "3d": "3D animation, same CG look in every frame.",
    "2d": "2D anime style, same line art and flat shading.",
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
