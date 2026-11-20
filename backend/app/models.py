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

    @field_validator("product_name", "description", "audience", "offer", mode="before")
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


class Scene(BaseModel):
    role: SceneRole
    description: str = Field(max_length=500, description="What the viewer sees in this scene")
    image_prompt: str = Field(
        max_length=1200,
        description="Prompt for the scene's reference image, built around the real product from the photo",
    )
    motion_prompt: str = Field(max_length=600, description="Camera and subject motion for the image-to-video clip")
    voiceover: str = Field(max_length=220, description="Voiceover line, about 5 seconds when spoken")
    on_screen_text: str = Field(default="", max_length=80)


class Hook(BaseModel):
    formula: HookFormula
    text: str = Field(max_length=160)


class Storyboard(BaseModel):
    """Three scenes (hook, demo, call to action) and three alternative hooks."""

    title: str = Field(max_length=100)
    scenes: list[Scene] = Field(min_length=3, max_length=3)
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    cta_text: str = Field(max_length=60)

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


class VariantView(BaseModel):
    label: str
    hook_idx: int
    status: str


class JobView(BaseModel):
    id: str
    status: str
    brief: Brief
    campaign_id: str | None = None
    brand: BrandKit | None = None
    flags: list[StoryboardFlag] = []
    variants: list[VariantView] = []
    analysis: ProductAnalysis | None = None
    storyboard: Storyboard | None = None
    attempts: int
    last_error: str | None = None
    stages: list[StageView] = []
    assets: list[AssetView] = []
    spend: Money
    cost_cap: Money
    created_at: str
