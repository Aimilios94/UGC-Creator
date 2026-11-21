"""Pydantic models: the brief, the AI outputs (validated structured outputs) and API views."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

Platform = Literal["tiktok", "instagram_reels", "youtube_shorts", "facebook"]
AspectRatio = Literal["9:16", "1:1", "4:5", "16:9"]
SceneRole = Literal["hook", "demo", "cta"]
HookFormula = Literal["pov", "problem_first", "three_reasons", "unboxing_tease"]
Goal = Literal["sales", "awareness", "traffic"]
Theme = Literal["sport", "beauty", "tech", "food", "fashion"]  # one YAML each in app/themes/ (M2 item 3)
AdType = Literal["testimonial", "product_demo", "unboxing", "problem_solution"]
Tone = Literal["energetic", "calm", "playful", "premium"]
Font = Literal["Inter", "Montserrat", "Bebas Neue", "Playfair Display"]  # bundled by compose (OFL)
Voice = Literal["marin", "cedar", "coral", "onyx", "none"]  # gpt-4o-mini-tts voices offered, or no voiceover
Music = Literal["theme", "none", "sport", "beauty", "tech", "food", "fashion"]  # the theme's bed, none, or any bed
MIN_SCENES, MAX_SCENES = 1, 5
CaptionStyle = Literal["bold", "clean", "off"]
VisualStyle = Literal["realistic", "cinematic", "3d", "2d"]
ImageSource = Literal["generate", "product", "upload"]
HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class Brief(BaseModel):
    """What the user typed. Treated as data in every prompt, never as instructions."""

    product_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=10, max_length=1000)
    audience: str = Field(default="", max_length=300)
    offer: str = Field(default="", max_length=200)  # offer or promo code, used verbatim
    landing_url: HttpUrl | None = None
    platform: Platform = "tiktok"
    aspect_ratio: AspectRatio = "9:16"
    goal: Goal | None = None
    theme: Theme | None = None
    ad_type: AdType | None = None
    voice: Voice = "marin"
    music: Music = "theme"
    captions: CaptionStyle = "bold"
    visual_style: VisualStyle = "realistic"
    story: str = Field(default="", max_length=4000)  # the user's own story or script, if any
    video_length_s: int | None = Field(default=None, ge=4, le=52)  # whole ad incl. end card; None = auto

    @field_validator("product_name", "description", "audience", "offer", "story", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class ProductAnalysis(BaseModel):
    """Vision LLM read of the product photo."""

    product_type: str = Field(description="What the product is, in a few words")
    visual_description: str = Field(
        description="Shape, colours, materials and packaging, precise enough to keep the product identical"
    )
    packaging_text: list[str] = Field(
        default_factory=list, description="Text visible on the product or packaging, verbatim"
    )
    key_features: list[str] = Field(default_factory=list, max_length=6)
    people_in_photo: bool = Field(description="True if a person or a face is visible in the photo")


class SceneDraft(BaseModel):
    """A scene as the AI writes it."""

    role: SceneRole
    description: str = Field(max_length=2500, description="What the viewer sees in this scene, in plain words")
    image_prompt: str = Field(
        max_length=2500,
        description="Detailed prompt for the scene's reference image (subject, setting, composition, camera, "
        "lighting, colours, style), built around the real product from the photo",
    )
    motion_prompt: str = Field(
        max_length=2200,
        description="Timed shot list for the image-to-video clip: what happens in each beat, camera and subject "
        "motion, lighting, focus, and how the shot ends",
    )
    voiceover: str = Field(
        default="", max_length=400, description="Spoken line for this scene (short enough for its length), or empty"
    )
    on_screen_text: str = Field(default="", max_length=80)
    duration_s: int = Field(
        default=5, ge=2, le=10, description="Seconds this scene is on screen, 2-10; follow the story's timing if given"
    )


def render_seconds(duration_s: int) -> int:
    """The video model makes 5 s or 10 s clips; a shorter scene is cut from the clip in compose."""
    return 5 if duration_s <= 5 else 10


class Scene(SceneDraft):
    """A scene with the user's choices: where its image comes from (and its length, above)."""

    uid: str = Field(default="", max_length=16)  # stable id, so joining or reordering keeps each scene's picture
    image_source: ImageSource = "generate"
    image_upload_key: str | None = None  # set by the server when the user uploads an image; never by the client


class Hook(BaseModel):
    formula: HookFormula
    text: str = Field(max_length=160)


def roles_for(n: int) -> list[str]:
    """Scene roles by position: the first opens (hook), the last closes (cta), the rest show (demo)."""
    if n == 1:
        return ["cta"]
    return ["hook", *(["demo"] * (n - 2)), "cta"]


def _roles_in_order(scenes):
    """The roles follow the scenes' order; they are set by position, whatever the writer sent.
    Every user scene gets a unique id (a copied or new scene gets a fresh one)."""
    roles = roles_for(len(scenes))
    seen: set[str] = set()
    for scene, role in zip(scenes, roles, strict=True):
        scene.role = role
        if hasattr(scene, "uid"):
            if not scene.uid or scene.uid in seen:
                scene.uid = uuid.uuid4().hex[:8]
            seen.add(scene.uid)
    return scenes


class StoryboardDraft(BaseModel):
    """Three scenes (hook, demo, call to action) and three alternative hooks, as the AI writes them."""

    title: str = Field(max_length=100)
    scenes: list[SceneDraft] = Field(min_length=MIN_SCENES, max_length=MAX_SCENES)
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    cta_text: str = Field(max_length=60)

    @field_validator("scenes")
    @classmethod
    def _draft_roles(cls, scenes):
        return _roles_in_order(scenes)


class Storyboard(BaseModel):
    """The storyboard the user edits and approves."""

    title: str = Field(max_length=100)
    scenes: list[Scene] = Field(min_length=MIN_SCENES, max_length=MAX_SCENES)
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    cta_text: str = Field(max_length=60)
    hook_choice: int | None = Field(default=None, ge=0, le=2)  # the hook idea used for scene 1, if any
    notes: str = Field(
        default="", max_length=4000
    )  # optional style and world notes, added to every scene's instructions
    continuity: Literal["continuous", "separate"] = "separate"  # continuous: each scene starts where the last ended

    @field_validator("scenes")
    @classmethod
    def _roles_by_position(cls, scenes: list[Scene]) -> list[Scene]:
        return _roles_in_order(scenes)


class BrandColors(BaseModel):
    primary: str | None = Field(default=None, pattern=HEX_COLOR)
    secondary: str | None = Field(default=None, pattern=HEX_COLOR)
    background: str | None = Field(default=None, pattern=HEX_COLOR)


class BrandKit(BaseModel):
    """Brand kit fields the user sets (plan §9). Where set, they override the theme's defaults."""

    tone: Tone | None = None
    colors: BrandColors = BrandColors()
    font: Font | None = None


class BrandSnapshot(BrandKit):
    """The brand kit as it was when the brief was sent; stored on the job."""

    logo_key: str | None = None


class StoryboardFlag(BaseModel):
    """A storyboard line that breaks the testimonial rule (plan §8 step 2)."""

    field: str  # e.g. "scenes.0.voiceover", "hooks.2.text", "cta_text"
    text: str
    reason: str


# --- API views ---------------------------------------------------------------
class Money(BaseModel):
    usd: float
    eur: float


class StageView(BaseModel):
    stage: str
    scene_idx: int
    status: str
    error: str | None = None


class AssetView(BaseModel):
    kind: str
    scene_idx: int | None = None
    ratio: str | None = None  # composed ads: "9:16", "1:1", ...
    name: str | None = None  # file name, e.g. "ad_9x16.mp4", "still_1.jpg"
    url: str
    content_type: str
    expires_in_s: int


class BrandKitView(BrandKit):
    logo_url: str | None = None
    updated_at: str


class CampaignView(BaseModel):
    id: str
    name: str
    goal: Goal | None = None
    audience: str
    offer: str
    landing_url: str | None = None
    ads: int
    created_at: str


class CostLine(BaseModel):
    kind: str  # llm | image | video | tts
    model: str
    calls: int
    cost: Money


class Estimate(BaseModel):
    images: Money  # reference images still to generate (own images are free)
    video: Money  # clips (by each scene's length) and voiceover
    total: Money
    fits_cap: bool


class VariantView(BaseModel):
    label: str
    hook_idx: int
    status: str
    duration_s: float | None = None
    ratios: list[str] = []  # ratios exported (passed the safe-zone check)
    skipped: dict[str, str] = {}  # ratio -> why it was not exported
    checks: list[dict] = []  # code-graded output checks per exported file


class SoundIn(BaseModel):
    """The ad's sound, changeable until the video is made."""

    voice: Voice | None = None
    music: Music | None = None
    captions: CaptionStyle | None = None


class ApproveIn(BaseModel):
    """What Approve makes: the images first (the user decides on the video after), or all in one go."""

    mode: Literal["images", "video"] = "images"


class JobView(BaseModel):
    id: str
    status: str
    brief: Brief
    campaign_id: str | None = None
    brand: BrandKit | None = None
    phase: str = "video"  # images (step 1) | video (step 2)
    costs: list[CostLine] = []  # what each AI cost so far
    flags: list[StoryboardFlag] = []
    variants: list[VariantView] = []
    estimate: Estimate | None = None
    analysis: ProductAnalysis | None = None
    storyboard: Storyboard | None = None
    attempts: int
    last_error: str | None = None
    stages: list[StageView] = []
    assets: list[AssetView] = []
    spend: Money
    cost_cap: Money
    created_at: str
