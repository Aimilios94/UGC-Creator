"""Upload guard: type and size checks, a real image decode, EXIF/GPS stripping.

The photo is decoded and re-encoded from pixels only, so no metadata (EXIF, GPS,
XMP, ICC comments) survives. The EXIF orientation is applied first, so the
re-encoded image looks the same. Large photos are scaled down.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from ..errors import UploadRejected

ALLOWED = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MAX_PIXELS = 40_000_000  # refuse decompression bombs before decoding


@dataclass
class CleanImage:
    data: bytes
    content_type: str
    ext: str
    width: int
    height: int
    sha256: str


def sanitise_image(raw: bytes, *, max_bytes: int, max_side: int) -> CleanImage:
    if not raw:
        raise UploadRejected("The file is empty.")
    if len(raw) > max_bytes:
        raise UploadRejected(f"The photo is larger than {max_bytes // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            if fmt not in ALLOWED:
                raise UploadRejected("Upload a JPEG, PNG or WebP photo.")
            if probe.width * probe.height > MAX_PIXELS:
                raise UploadRejected("The photo has too many pixels.")
            probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except UploadRejected:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise UploadRejected("The file is not a readable image.") from None

    img = ImageOps.exif_transpose(img)
    keep_alpha = fmt == "PNG" and img.mode in ("RGBA", "LA", "P")
    img = img.convert("RGBA" if keep_alpha else "RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    # A fresh image from pixels only: nothing from the original file's metadata is copied.
    clean = Image.new(img.mode, img.size)
    clean.paste(img)
    buf = io.BytesIO()
    if keep_alpha:
        clean.save(buf, "PNG", optimize=True)
        content_type, ext = "image/png", "png"
    else:
        clean.save(buf, "JPEG", quality=92, optimize=True)
        content_type, ext = "image/jpeg", "jpg"
    data = buf.getvalue()
    return CleanImage(
        data=data,
        content_type=content_type,
        ext=ext,
        width=clean.width,
        height=clean.height,
        sha256=hashlib.sha256(data).hexdigest(),
    )
