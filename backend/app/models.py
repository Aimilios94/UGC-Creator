"""Pydantic models: the brief, the AI outputs (validated structured outputs) and API views."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

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
# A "scene" in the storyboard is one shot: one clip, one cut (D32). The user's story may have as many
# cuts as it wants, up to MAX_SCENES shots; a length or "Add scenes" plans at most MAX_PLANNED_SCENES.
MIN_SCENES, MAX_SCENES = 1, 20
MAX_PLANNED_SCENES = 5
MIN_SHOT_S = 1  # a rapid cut can be 1 second on screen (the video model still makes 5 s)
Cutting = Literal["auto", "flowing", "cuts", "separate"]  # "How it's cut" on the Create page (D32)
Join = Literal["flow", "cut"]  # how a shot meets the one before it
ShotKind = Literal["clip", "card"]  # card: the story's own end card (logo, brand reveal), drawn by us
STORY_MAX = 12000  # the user's story and its style notes, in characters (D30)
SPLIT_NOTE_MAX = 600  # the line saying how the story was split into scenes (D31)
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
    story: str = Field(default="", max_length=STORY_MAX)  # the user's own story or script, if any
    video_length_s: int | None = Field(default=None, ge=4, le=52)  # whole ad incl. end card; None = auto
    # auto: flows where the story continues, cuts where it says so or the person or place changes;
    # flowing: one flowing take (a new person or place still cuts); cuts: a hard cut at every shot;
    # separate: separate shots with a soft blend (D32).
    cutting: Cutting = "auto"

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
    # Strategy plan A4: a person whose face shows is the character reference for every picture of them.
    face_visible: bool = Field(default=False, description="True if a person's face is clearly visible in the photo")
    person_look: str = Field(
        default="",
        max_length=300,
        description="When a face is visible: how that person looks (face, hair, skin tone, age range, build), "
        "else empty",
    )


class SceneDraft(BaseModel):
    """A scene as the AI writes it."""

    role: SceneRole
    description: str = Field(max_length=STORY_MAX, description="What the viewer sees in this scene, in plain words")
    image_prompt: str = Field(
        max_length=STORY_MAX,
        description="Detailed prompt for the scene's reference image (subject, setting, composition, camera, "
        "lighting, colours, style), built around the real product from the photo",
    )
    motion_prompt: str = Field(
        max_length=STORY_MAX,  # Kling reads 2,500 per clip: checked per clip, never cut (D30)
        description="Timed shot list for the image-to-video clip: what happens in each beat, camera and subject "
        "motion, lighting, focus, and how the shot ends",
    )
    voiceover: str = Field(
        default="", max_length=400, description="Spoken line for this scene (short enough for its length), or empty"
    )
    on_screen_text: str = Field(default="", max_length=80)
    # Suggestions the user can pick from; the fields above start empty unless the user's story gives
    # the words (owner, 22 Nov 2026: nothing is spoken or shown in the video unless the user chose it).
    voiceover_ideas: list[Annotated[str, Field(max_length=400)]] = Field(
        default_factory=list, max_length=3, description="2-3 short spoken lines that fit the scene, to pick from"
    )
    text_ideas: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=3, description="2-3 short on-screen headlines, to pick from"
    )
    duration_s: int = Field(
        default=5,
        ge=MIN_SHOT_S,
        le=10,
        description="Seconds this scene is on screen, 1-10 (usually 2-10); follow the story's timing if given",
    )


def render_seconds(duration_s: int) -> int:
    """The video model makes 5 s or 10 s clips; a shorter scene is cut from the clip in compose."""
    return 5 if duration_s <= 5 else 10


class Scene(SceneDraft):
    """A scene with the user's choices: where its image comes from (and its length, above)."""

    uid: str = Field(default="", max_length=16)  # stable id, so joining or reordering keeps each scene's picture
    image_source: ImageSource = "generate"
    image_upload_key: str | None = None  # set by the server when the user uploads an image; never by the client
    # How the shot opens and how it ends, so each cut matches (D30): written by the continuity check
    # after the writer, only for the picture and video AI, never shown as story text.
    starts: str = Field(default="", max_length=800)
    ends: str = Field(default="", max_length=800)
    # The style and world notes cut down to what this scene needs, so its clip fits Kling's 2,500
    # characters; used only when the full notes do not fit (D30).
    notes_short: str = Field(default="", max_length=2500)
    # Added by "Add scenes to reach N s" (plan v2.3): the AI's guess, marked on the page, with Undo.
    ai_added: bool = False
    # Scenes and shots (D32): shots cut from one part of the user's story share its number (0 = its
    # own part); `join` says how this shot meets the one before (flows on from its last frame, or a
    # cut to a new picture); a "card" shot is the story's own end card, drawn by us, never filmed.
    part: int = Field(default=0, ge=0, le=MAX_SCENES)
    join: Join = "flow"
    kind: ShotKind = "clip"


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


class ActionSwap(BaseModel):
    """The writer's safe version of a user's action that the video AI does badly (strategy plan A1)."""

    scene: int = Field(ge=1, le=MAX_SCENES, description="The scene's number")
    action: str = Field(max_length=STORY_MAX, description="The scene's text with the weak spot changed, the rest kept")
    reason: str = Field(max_length=200, description='A short reason, for example "Kling renders throws badly"')


class SheetFix(BaseModel):
    """The writer's corrected guess for a cast and world value that contradicts the user's words or
    answers (D31 phase 5); code applies it only to a value that is still the AI's guess."""

    slot: Literal["place", "time_light", "look", "camera_style", "never", "product_unseen"]
    value: str = Field(max_length=600)


class StoryboardDraft(BaseModel):
    """Three scenes (hook, demo, call to action) and three alternative hooks, as the AI writes them."""

    title: str = Field(max_length=100)
    scenes: list[SceneDraft] = Field(min_length=MIN_SCENES, max_length=MAX_SCENES)
    hooks: list[Hook] = Field(min_length=3, max_length=3)
    cta_text: str = Field(max_length=60)
    swaps: list[ActionSwap] = Field(
        default_factory=list,
        max_length=MAX_SCENES,
        description="Only with a <sheet>: user actions the video AI does badly, swapped (else empty)",
    )
    sheet_fixes: list[SheetFix] = Field(
        default_factory=list,
        max_length=6,
        description="Only with a <sheet>: guessed values that contradict the user's words or answers, corrected",
    )

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
        default="", max_length=STORY_MAX
    )  # optional style and world notes, added to every scene's instructions
    # continuous (the default since D30): every scene flows into the next; separate: cuts between shots
    continuity: Literal["continuous", "separate"] = "continuous"
    # What stays the same in every scene (camera language, people, clothes, place, light), from the
    # continuity check (D30); added to the AI instructions in a continuous shot only.
    keep_same: str = Field(default="", max_length=1200)
    # How the story was read into scenes, in one plain line ("3 scenes from your scene headings ..."),
    # with any scenes joined or split (D31); empty when the writer read the story whole.
    split_note: str = Field(default="", max_length=SPLIT_NOTE_MAX)
    # The ad read into the fixed structure by the slot filler (D31 phase 3): the cast and world sheet
    # and a card per scene (matched by the scene's uid), every value marked as the user's or the
    # AI's guess. Set by the server only; kept as plain data here (`ad_structure.AdStructure`).
    structure: dict | None = None

    @field_validator("scenes")
    @classmethod
    def _roles_by_position(cls, scenes: list[Scene]) -> list[Scene]:
        for sc in scenes[:-1]:
            sc.kind = "clip"  # only the last shot can be the story's own end card (D32)
        if len(scenes) == 1:
            scenes[0].kind = "clip"  # an ad needs at least one filmed shot
        return _roles_in_order(scenes)

    @field_validator("structure")
    @classmethod
    def _valid_structure(cls, v: dict | None) -> dict | None:
        if v is None:
            return None
        from .services.ad_structure import AdStructure  # the structure module imports this one

        return AdStructure.model_validate(v).model_dump(mode="json")


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
    scene_uid: str | None = None  # own pictures: the scene that uses it now (scenes can be moved)
    ratio: str | None = None  # composed ads: "9:16", "1:1", ...
    name: str | None = None  # file name, e.g. "ad_9x16.mp4", "still_1.jpg"
    url: str
    content_type: str
    expires_in_s: int
    width: int | None = None  # pictures: lets the page show when an own picture must be extended (D31)
    height: int | None = None


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


class ClipPartView(BaseModel):
    """One part of a clip's text against its budget (strategy plan, the clip builder)."""

    name: str
    chars: int
    budget: int


class ClipView(BaseModel):
    """The exact text a scene's clip gets (Kling reads at most 2,500 characters, D30)."""

    text: str
    chars: int
    limit: int
    too_long_by: int = 0  # the scene's own text is this much over: shorten it (or "Shorten it for me")
    notes: str = "none"  # full | short | none: which style and world notes went in
    parts: list[ClipPartView] = []  # built from the structure: each part and its budget (phase 4)
    negative: str = ""  # Kling's separate negative prompt
    shorten_field: str = "motion_prompt"  # the scene field "Shorten it for me" rewrites


class ShortenOut(BaseModel):
    text: str
    field: str = "motion_prompt"  # description | motion_prompt: where the shorter text goes


class LengthLine(BaseModel):
    """Plan v2.3: the scenes make another length than the one picked; said plainly, never stretched."""

    real_s: int
    picked_s: int
    text: str  # "Your scenes make a 22 s ad (you picked 40 s)."
    add: str = ""  # "Add scenes to reach 40 s", or empty when no scene can be added
    add_lengths: list[int] = []
    keep: str  # "Keep 22 s"


class QuestionView(BaseModel):
    """A quick question before the storyboard (D31 phase 5): suggestion buttons, a free-text box,
    "Let the AI decide" (the default) and Skip all."""

    slot: str
    text: str
    options: list[str]
    let_ai_decide: str = "Let the AI decide"


class AnswersIn(BaseModel):
    """Answers by slot; an empty or missing answer is "Let the AI decide". `skip` keeps every guess."""

    answers: dict[str, str] = Field(default_factory=dict, max_length=5)
    skip: bool = False


class LengthIn(BaseModel):
    video_length_s: int = Field(ge=4, le=52)


NO_PHOTO_NOTE = "Add a photo so your product looks exactly right."  # strategy plan A6


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
    length_line: LengthLine | None = None  # plan v2.3, on the storyboard only
    questions: list[QuestionView] = []  # quick questions waiting before the storyboard (D31 phase 5)
    clips: list[ClipView] = []  # what each scene's clip gets (D30)
    analysis: ProductAnalysis | None = None
    has_photo: bool = True  # False: no product photo, the pictures are made from the brief (plan A6)
    photo_note: str = ""  # with no photo, the one plain note the storyboard shows (NO_PHOTO_NOTE)
    storyboard: Storyboard | None = None
    attempts: int
    last_error: str | None = None
    stages: list[StageView] = []
    assets: list[AssetView] = []
    spend: Money
    cost_cap: Money
    created_at: str
