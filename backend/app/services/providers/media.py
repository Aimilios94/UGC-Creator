"""Image and video generation behind one interface: fal (real) or mock (tests, CI, local dev).

Every render is asynchronous: submit returns a prediction ID that the pipeline saves
at once, then it polls. A re-attempt polls the saved ID instead of paying again.

fal privacy settings on every request:
- `X-Fal-Store-IO: 0` turns off fal's request-history storage of inputs and outputs.
- `X-Fal-Object-Lifecycle-Preference` makes fal delete its copy of each output after
  `fal_output_expiry_s` (fal keeps outputs forever and publicly readable by default);
  the worker copies every output into our own storage first.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import httpx

from ...config import Settings
from ...errors import ProviderNotConfigured

MOCK_CLIP = Path(__file__).with_name("mock_assets") / "clip.mp4"


@dataclass
class InputImage:
    data: bytes
    content_type: str
    url: str | None = None  # set when storage can give the provider a URL (GCS)


@dataclass
class MediaRequest:
    kind: Literal["image", "video"]
    model: str
    arguments: dict
    input_image: InputImage | None  # None: a picture made from text only (no product photo, plan A6)
    image_field: str  # "image_urls" (list) or "image_url"; unused when there is no input picture
    # The picture the clip must end on (Kling `tail_image_url`, D30): the next scene's own picture.
    tail_image: InputImage | None = None
    tail_field: str = "tail_image_url"
    # More reference pictures after the product photo ("image_urls" only): the first picture of
    # each person in the shot, so the same face comes back in every shot (strategy plan A4).
    extra_images: list[InputImage] = field(default_factory=list)


@dataclass
class MediaResult:
    content_type: str
    url: str | None = None
    data: bytes | None = None
    width: int | None = None
    height: int | None = None


class MediaError(RuntimeError):
    """Transient: polling failed or timed out. The render may still finish; poll it again."""


class MediaFailed(MediaError):
    """The provider finished the render with an error. Polling again will not help."""


class MediaProvider(Protocol):
    name: str

    def submit(self, req: MediaRequest) -> str: ...
    def status(self, model: str, prediction_id: str) -> Literal["queued", "running", "done"]: ...
    def result(self, model: str, prediction_id: str, kind: str) -> MediaResult: ...
    def download(self, result: MediaResult) -> bytes: ...


def _parse_output(kind: str, out: dict) -> MediaResult:
    if kind == "image":
        images = out.get("images") or []
        if not images:
            raise MediaFailed("the image model returned no image")
        img = images[0]
        return MediaResult(
            content_type=img.get("content_type") or "image/jpeg",
            url=img["url"],
            width=img.get("width"),
            height=img.get("height"),
        )
    video = out.get("video") or {}
    if not video.get("url"):
        raise MediaFailed("the video model returned no video")
    return MediaResult(content_type=video.get("content_type") or "video/mp4", url=video["url"])


class FalMedia:
    name = "fal"

    def __init__(self, key: str, *, output_expiry_s: int = 3600, client=None, http: httpx.Client | None = None):
        if not key:
            raise ProviderNotConfigured("FAL_KEY is not set")
        if client is None:
            import fal_client

            client = fal_client.SyncClient(key=key)
        self._client = client
        self._expiry = output_expiry_s
        self._http = http or httpx.Client(timeout=120, follow_redirects=True)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-Fal-Store-IO": "0",
            "X-Fal-Object-Lifecycle-Preference": json.dumps({"expiration_duration_seconds": self._expiry}),
        }

    def _input_url(self, image: InputImage) -> str:
        if image.url:
            return image.url
        from fal_client import StorageSettings

        # Local dev: the file is on this machine, so fal gets a short-lived copy on its CDN.
        return self._client.upload(image.data, image.content_type, lifecycle=StorageSettings(expires_in=self._expiry))

    def submit(self, req: MediaRequest) -> str:
        args = dict(req.arguments)
        url = self._input_url(req.input_image) if req.input_image is not None else None
        if url is None:
            pass  # text to image: no picture goes in
        elif req.image_field == "image_urls":
            args[req.image_field] = [url, *(self._input_url(x) for x in req.extra_images)]
        else:
            args[req.image_field] = url
        if req.tail_image is not None:
            args[req.tail_field] = self._input_url(req.tail_image)
        handle = self._client.submit(req.model, args, headers=self.headers)
        return handle.request_id

    def status(self, model: str, prediction_id: str):
        import fal_client

        s = self._client.status(model, prediction_id)
        if isinstance(s, fal_client.Completed):
            if getattr(s, "error", None):
                raise MediaFailed(f"fal reported an error: {s.error_type or ''} {s.error}".strip())
            return "done"
        if isinstance(s, fal_client.InProgress):
            return "running"
        return "queued"

    def result(self, model: str, prediction_id: str, kind: str) -> MediaResult:
        return _parse_output(kind, self._client.result(model, prediction_id))

    def download(self, result: MediaResult) -> bytes:
        if result.data is not None:
            return result.data
        r = self._http.get(result.url)
        r.raise_for_status()
        return r.content


_RATIO_SIZES = {"9:16": (540, 960), "1:1": (720, 720), "4:5": (640, 800), "16:9": (960, 540)}


@dataclass
class MockMedia:
    """Deterministic renders with no network. Costs are priced as the real model it stands in for."""

    name: str = "mock"
    submits: list[MediaRequest] = field(default_factory=list)
    fail_status_times: int = 0  # simulate a crash while polling, for resume tests
    # Local stack: show the user's own pictures (a "picture" is the product photo fitted to the frame,
    # a "clip" is its input picture with a slow camera move) instead of plain placeholders. Tests keep
    # the fast placeholders.
    preview: bool = False

    def submit(self, req: MediaRequest) -> str:
        self.submits.append(req)
        digest = hashlib.sha256(json.dumps(req.arguments, sort_keys=True).encode()).hexdigest()[:16]
        return f"mock-{req.kind}-{digest}-{len(self.submits)}"

    def status(self, model: str, prediction_id: str):
        if self.fail_status_times > 0:
            self.fail_status_times -= 1
            raise MediaError("simulated crash while polling")
        return "done"

    def _request(self, prediction_id: str) -> MediaRequest | None:
        try:
            return self.submits[int(prediction_id.rsplit("-", 1)[1]) - 1]
        except (ValueError, IndexError):
            return None

    def result(self, model: str, prediction_id: str, kind: str) -> MediaResult:
        req = self._request(prediction_id) if self.preview else None
        if kind == "video":
            if req is not None and req.input_image is not None and req.input_image.data:
                seconds = int(req.arguments.get("duration", "5"))
                tail = req.tail_image.data if req.tail_image is not None else None
                return MediaResult(content_type="video/mp4", data=_mock_clip(req.input_image.data, seconds, tail))
            return MediaResult(content_type="video/mp4", data=MOCK_CLIP.read_bytes())
        ratio = prediction_id_ratio(self.submits, prediction_id)
        w, h = _RATIO_SIZES.get(ratio, (540, 960))
        if req is not None and req.input_image is not None and req.input_image.data:
            data = _mock_picture(req.input_image.data, w, h)
        else:
            data = _mock_image(w, h, prediction_id)
        return MediaResult(content_type="image/jpeg", data=data, width=w, height=h)

    def download(self, result: MediaResult) -> bytes:
        return result.data or b""


def prediction_id_ratio(submits: list[MediaRequest], prediction_id: str) -> str:
    try:
        n = int(prediction_id.rsplit("-", 1)[1])
        return submits[n - 1].arguments.get("aspect_ratio", "9:16")
    except (ValueError, IndexError):
        return "9:16"


def _mock_image(w: int, h: int, label: str) -> bytes:
    from PIL import Image, ImageDraw

    seed = int(hashlib.sha256(label.encode()).hexdigest()[:6], 16)
    img = Image.new("RGB", (w, h), ((seed >> 16) & 0x7F, (seed >> 8) & 0x7F, seed & 0x7F))
    d = ImageDraw.Draw(img)
    d.rectangle([w * 0.25, h * 0.3, w * 0.75, h * 0.7], outline=(255, 255, 255), width=4)
    d.text((w * 0.27, h * 0.32), "MOCK RENDER", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _mock_picture(photo: bytes, w: int, h: int) -> bytes:
    """Local preview of a "generated" picture: the product photo fitted to the frame, marked as a test."""
    from PIL import Image, ImageDraw, ImageOps

    with Image.open(io.BytesIO(photo)) as src:
        img = ImageOps.fit(src.convert("RGB"), (w, h))
    d = ImageDraw.Draw(img)
    d.rectangle([0, h - 28, w, h], fill=(0, 0, 0))
    d.text((10, h - 22), "TEST PICTURE (no AI on the local stack)", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _mock_clip(picture: bytes, seconds: int, tail: bytes | None = None) -> bytes:
    """Local preview of a clip: the scene's starting picture with a slow push-in (no AI motion).
    With an end picture, the clip moves on to it and its last frame is that picture, as Kling's
    end frame does, so a cut to the next scene matches."""
    import subprocess
    import tempfile

    from PIL import Image, ImageOps

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.png"
        dst = Path(tmp) / "out.mp4"
        frames = seconds * 25
        with Image.open(io.BytesIO(picture)) as im:  # the clip keeps the picture's shape, as Kling does
            w, h = (
                (540, round(540 * im.height / im.width / 2) * 2)
                if im.width < im.height
                else (round(540 * im.width / im.height / 2) * 2, 540)
            )
            ImageOps.fit(im.convert("RGB"), (w, h)).save(src)
        move = (
            f"scale={w * 2}:{h * 2},zoompan=z='min(zoom+0.0012,1.2)':d={frames}:x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=25"
        )
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
        if tail is None:
            args += ["-vf", move]
        else:
            end = Path(tmp) / "tail.png"
            with Image.open(io.BytesIO(tail)) as im:
                ImageOps.fit(im.convert("RGB"), (w, h)).save(end)
            fade = round(seconds * 0.4, 2)
            args += [
                "-loop",
                "1",
                "-t",
                str(seconds),
                "-i",
                str(end),
                "-filter_complex",
                f"[0:v]{move},trim=duration={seconds},setpts=PTS-STARTPTS,fps=25[a];"
                f"[1:v]fps=25,setsar=1,format=yuv420p,trim=duration={seconds},setpts=PTS-STARTPTS,fps=25[b];"
                f"[a]format=yuv420p,setsar=1[a2];[a2][b]xfade=transition=fade:duration={fade}:"
                f"offset={seconds - fade - 0.04:.2f}[v]",
                "-map",
                "[v]",
            ]
        args += ["-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dst)]
        subprocess.run(args, check=True)  # noqa: S603 - argument list, no shell; ffmpeg from PATH
        return dst.read_bytes()


def wait_for(
    provider: MediaProvider,
    model: str,
    prediction_id: str,
    *,
    timeout_s: float,
    interval_s: float,
    sleep=time.sleep,
    clock=time.monotonic,
) -> None:
    deadline = clock() + timeout_s
    while True:
        if provider.status(model, prediction_id) == "done":
            return
        if clock() >= deadline:
            raise MediaError(f"render {prediction_id} not finished after {int(timeout_s)} s")
        sleep(interval_s)


class UnavailableMedia:
    """Stands in where rendering never happens (the API service): it holds no fal key."""

    name = "unavailable"

    def _refuse(self, *args, **kwargs):
        raise ProviderNotConfigured("this process does not render; the worker does")

    submit = status = result = download = _refuse


def build_media_or_unavailable(settings: Settings) -> MediaProvider:
    return build_media(settings) if settings.media_configured else UnavailableMedia()


def build_media(settings: Settings) -> MediaProvider:
    if settings.media_provider == "mock":
        return MockMedia(preview=settings.mock_preview)
    if settings.media_provider == "fal":
        return FalMedia(settings.fal_key, output_expiry_s=settings.fal_output_expiry_s)
    raise ProviderNotConfigured(f"unknown MEDIA_PROVIDER {settings.media_provider!r}")
