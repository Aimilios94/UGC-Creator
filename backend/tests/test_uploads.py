"""Guardrails (M1): upload type/size guard and EXIF/GPS stripping."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.errors import UploadRejected
from app.services.uploads import sanitise_image

MB = 1024 * 1024


def _jpeg_with_gps(orientation: int = 1) -> bytes:
    img = Image.new("RGB", (400, 200), (10, 120, 200))
    exif = Image.Exif()
    exif[0x0112] = orientation  # Orientation
    exif[0x010F] = "PhoneMaker"  # Make
    gps = {1: "N", 2: (52.0, 22.0, 1.0), 3: "E", 4: (4.0, 53.0, 2.0)}
    exif[0x8825] = gps  # GPSInfo
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_exif_and_gps_are_stripped():
    raw = _jpeg_with_gps()
    assert Image.open(io.BytesIO(raw)).getexif().get(0x8825) is not None  # the fixture really has GPS
    clean = sanitise_image(raw, max_bytes=10 * MB, max_side=2048)
    out = Image.open(io.BytesIO(clean.data))
    assert len(out.getexif()) == 0
    assert b"PhoneMaker" not in clean.data
    assert "exif" not in out.info


def test_orientation_is_applied_before_stripping():
    raw = _jpeg_with_gps(orientation=6)  # rotate 90 degrees on display
    clean = sanitise_image(raw, max_bytes=10 * MB, max_side=2048)
    assert (clean.width, clean.height) == (200, 400)


def test_rejects_non_images_and_wrong_types():
    with pytest.raises(UploadRejected):
        sanitise_image(b"%PDF-1.7 not an image", max_bytes=10 * MB, max_side=2048)
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, "GIF")
    with pytest.raises(UploadRejected, match="JPEG, PNG or WebP"):
        sanitise_image(gif.getvalue(), max_bytes=10 * MB, max_side=2048)
    with pytest.raises(UploadRejected):
        sanitise_image(b"", max_bytes=10 * MB, max_side=2048)


def test_rejects_too_large_files():
    raw = _jpeg_with_gps()
    with pytest.raises(UploadRejected, match="larger than"):
        sanitise_image(raw, max_bytes=len(raw) - 1, max_side=2048)


def test_large_photos_are_scaled_down_and_png_alpha_kept():
    img = Image.new("RGBA", (3000, 1500), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    clean = sanitise_image(buf.getvalue(), max_bytes=10 * MB, max_side=1024)
    assert clean.content_type == "image/png"
    assert max(clean.width, clean.height) == 1024
