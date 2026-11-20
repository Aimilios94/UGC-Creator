"""Pydantic models: the brief, the AI outputs (validated structured outputs) and API views."""

from __future__ import annotations

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
Voice = Literal["marin", "cedar", "coral", "onyx"]  # gpt-4o-mini-tts built-in voices offered
Music = Literal["theme", "none"]
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
    description: str = Field(max_length=800, description="What the viewer sees in this scene, in plain words")
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
    voiceover: str = Field(max_length=220, description="Voiceover line, about 5 seconds when spoken")
    on_screen_text: str = Field(default="", max_length=80)


class Scene(SceneDraft):
    """A scene with the user's choices: clip length and where its image comes from."""

    duration_s: Literal[5, 10] = 5
    image_source: ImageSource = "generate"
    image_upload_key: str | None = None  # set by the server when the user uploads an image; never by the client


class Hook(BaseModel):
    formula: HookFormula
    text: str = Field(max_length=160)


def _roles_in_order(scenes):
    if [s.role for s in scenes] != ["hook", "demo", "cta"]:
        raise ValueError("scenes must be hook, demo, cta in that order")
    return scenes


class StoryboardDraft(BaseModel):
    """Three scenes (hook, demo, call to action) and three alternative hooks, as the AI writes them."""

    title: str = Field(max_length=100)
    scenes: list[SceneDraft] = Field(min_length=3, max_length=3)
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    cta_text: str = Field(max_length=60)

    @field_validator("scenes")
    @classmethod
    def _draft_roles(cls, scenes):
        return _roles_in_order(scenes)


class Storyboard(BaseModel):
    """The storyboard the user edits and approves."""

    title: str = Field(max_length=100)
    scenes: list[Scene] = Field(min_length=3, max_length=3)
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    cta_text: str = Field(max_length=60)
    hook_choice: int | None = Field(default=None, ge=0, le=2)  # the hook idea used for scene 1, if any

    @field_validator("scenes")
    @classmethod
    def _roles_in_order(cls, scenes: list[Scene]) -> list[Scene]:
        if [s.role for s in scenes] != ["hook", "demo", "cta"]:
            raise ValueError("scenes must be hook, demo, cta in that order")
        return scenes


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


class JobView(BaseModel):
    id: str
    status: str
    brief: Brief
    campaign_id: str | None = None
    brand: BrandKit | None = None
    phase: str = "video"  # images (step 1) | video (step 2)
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
