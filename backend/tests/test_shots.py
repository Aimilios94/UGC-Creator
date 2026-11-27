"""Scenes and shots (D32): free cuts, "How it's cut", the story's own end card, and the fixes from the
owner's real-AI storyboard test of 26 Nov 2026 (feedback-notes, round 4)."""

from __future__ import annotations

import pytest

from app import worker
from app.models import Brief, Scene, Storyboard
from app.services import compose as C
from app.services.ad_structure import AdStructure, CastRefs, Person, SceneCard, Slot
from app.services.pipeline import ends_on_next_picture, estimate_board_usd, is_chained
from app.services.providers.media import MOCK_CLIP
from app.services.providers.voice import MockVoice, VoiceRequest
from app.services.scene_plan import scenes_for_length
from app.services.scene_splitter import card_sentence, fast_story, split_story, story_length_s
from app.services.shots import plan_joins, split_end_card, voice_rooms
from app.services.slot_filler import SlotOut, _slot, code_questions, content_words, named_in_story, open_questions
from app.services.storyboard import fill_placeholders, packed_scenes, target_scenes
from app.services.storyboard_checks import flag_testimonials
from app.services.video_gen import _clause_cut, _with_subject, film_only, negative_prompt
from conftest import BRIEF, make_settings
from helpers import create_job, to_video

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

SPORT = (
    "Gritty pre-dawn sports film, anamorphic look. "
    "[0:00-0:04] Close-up of a runner lacing up her shoes in the dark; audio: the snap of the laces. "
    "[0:04-0:10] Rapid cuts of chalk clapping off hands, rain hitting a basketball court, and a swimmer "
    'breaking the water surface; a calm voiceover says: "Nobody claps at dawn." '
    "[0:10-0:14] She sprints up the stadium stairs, sweat flying. "
    '[0:14-0:16] Hard cut to black as a white logo slams onto the screen; voiceover: "Own the dawn. [Brand Name]."'
)


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


# --- the splitter: brackets, quick cuts, the end card ------------------------------------------------
def test_quick_cuts_become_shots_in_one_part_and_a_logo_ending_becomes_the_end_card():
    split = split_story(SPORT)
    assert split.notes == "Gritty pre-dawn sports film, anamorphic look."  # no stray "[" left
    texts = [b.text for b in split.beats]
    assert texts[0].startswith("0:00-0:04 Close-up of a runner") and "[0:" not in " ".join(texts)
    assert not any(t.rstrip().endswith("[") for t in texts)
    assert [b.part for b in split.beats] == [1, 2, 2, 2, 3, 4]
    assert [b.seconds for b in split.beats] == [4, 2, 2, 2, 4, 2]
    assert [b.join for b in split.beats] == ["", "cut", "cut", "cut", "", ""]
    assert texts[1].startswith("0:04-0:10 Chalk clapping off hands") and "Nobody claps at dawn" in texts[1]
    assert texts[2] == "Rain hitting a basketball court" and texts[3] == "A swimmer breaking the water surface"
    assert [b.card for b in split.beats] == [False] * 5 + [True]
    assert "quick cuts became 3 shots" in split.summary() and "end card" in split.summary()


def test_an_ordinary_list_or_last_scene_is_not_a_montage_or_a_card():
    split = split_story("Scene 1: he walks and smiles.\nScene 2: she holds the mug, and the steam rises.")
    assert len(split.beats) == 2 and not any(b.card for b in split.beats) and not split.messages


# --- how shots join -----------------------------------------------------------------------------------
def _board(n: int, **scene_kw) -> Storyboard:
    scenes = [Scene(role="demo", description=f"shot {i}", image_prompt="", motion_prompt="", **scene_kw)
              for i in range(n)]  # fmt: skip
    return Storyboard(title="T", scenes=scenes, hooks=[{"formula": "pov", "text": "h"}] * 3, cta_text="Shop")


def _with_cards(board: Storyboard, who: list[list[str]], places: list[str]) -> Storyboard:
    cards = [
        SceneCard(uid=sc.uid, who=CastRefs(ids=w), place_change=Slot(value=p))
        for sc, w, p in zip(board.scenes, who, places, strict=True)
    ]
    people = [Person(id=i, label=i) for i in sorted({x for w in who for x in w if x != "product"})]
    ad = AdStructure(sheet={"people": people}, scenes=cards)
    board.structure = ad.model_dump(mode="json")
    return board


HOODIE = (
    "A stylish, 20-second lifestyle commercial celebrating the creative spirit of artists. It follows a creator "
    "in unexpected urban spaces: a rain-slicked alley, a quiet bridge at dawn, and a bustling studio late at night. "
    "Through poetic, fast-paced shots emphasizing texture, movement, and raw creativity, it captures the idea of "
    "wearing your art as armor. The ad culminates in a sharp, minimalist reveal of the brand logo, positioning the "
    "hoodie as a statement of identity."
)


def test_a_logo_reveal_on_the_product_stays_filmed_and_the_end_card_follows():
    board = _with_cards(_board(3), [["P1"]] * 3, ["", "", ""])
    board.scenes[2].description = "Wearing your art as armor. " + HOODIE.split(". ")[-1]
    board.scenes[2].motion_prompt = "0-2 s: push in; focus tightens on the brand logo."
    assert split_end_card(board, 2.0)
    last, card = board.scenes[-2], board.scenes[-1]
    assert len(board.scenes) == 4 and card.kind == "card" and card.duration_s == 2
    # No shot is lost: the reveal stays filmed, its logo words made "the print" (D31, D32).
    assert last.kind == "clip" and "armor" in last.description and "reveal of the print" in last.description
    assert "logo" not in last.description.casefold() and "logo" not in last.motion_prompt.casefold()
    assert len(board.structure["scenes"]) == 4 and board.structure["scenes"][-1]["uid"] == card.uid
    assert "end card" in board.split_note
    Storyboard.model_validate(board.model_dump())  # still a valid storyboard
    # Already a card, or no logo: nothing changes.
    assert not split_end_card(board, 2.0)
    assert not split_end_card(_board(3), 2.0)


def test_a_logo_graphic_on_screen_becomes_the_end_card():
    board = _board(3)
    board.scenes[2].description = "She smiles at the camera. Cut to black as a white logo slams onto the screen."
    assert split_end_card(board, 2.0)
    assert [s.kind for s in board.scenes] == ["clip", "clip", "clip", "card"]
    assert "logo" not in board.scenes[2].description and "slams" in board.scenes[3].description
    whole = _board(3)  # the whole shot is the graphic: it is the card
    whole.scenes[2].description = "A white logo slams onto a black screen."
    assert split_end_card(whole, 2.0) and [s.kind for s in whole.scenes] == ["clip", "clip", "card"]


def test_a_one_sentence_shot_keeps_its_filmed_moment_and_only_the_logo_becomes_the_card():
    # The owner's hoodie remake (27 Nov 2026): the nod was lost because the whole sentence became the card.
    board = _board(3)
    last = board.scenes[2]
    last.description = (
        "The creator faces the camera in the studio doorway, gives a quiet confident nod with the hood down; "
        "the frame then goes to black for a sharp minimalist brand logo reveal in edit."
    )
    last.motion_prompt = (
        "0-2 s: push-in as the creator nods. 2-4 s: the frame tightens on the chest artwork; final frame "
        "centers on the hoodie chest before the screen goes dark for the brand logo reveal in edit."
    )
    assert split_end_card(board, 2.0)
    assert [s.kind for s in board.scenes] == ["clip", "clip", "clip", "card"]
    kept, card = board.scenes[2], board.scenes[3]
    assert kept.description.endswith("with the hood down.") and "logo" not in kept.description
    assert kept.motion_prompt.endswith("centers on the hoodie chest.") and "dark" not in kept.motion_prompt
    assert card.description.startswith("The frame then goes to black") and card.duration_s == 2
    assert card_sentence("The logo slams onto black.") == ("", "The logo slams onto black.")
    assert card_sentence("A slow walk; she waves before the sun sets.") is None
    # The reveal is not the last sentence: a sentence after it still about the logo goes with it.
    real = (
        "A sharp minimalist brand reveal: cut to black, then the Nomad Atelier logo and a close linger on hoodie "
        "fabric texture and art as the brand emblem appears. The ad ends on the logo."
    )
    assert card_sentence(real) == ("", real)
    whole = _board(3)
    whole.scenes[2].description = real
    assert split_end_card(whole, 2.0) and [s.kind for s in whole.scenes] == ["clip", "clip", "card"]
    assert card_sentence("She waves. The logo slams onto black. She laughs.") is None  # a filmed moment after it


def test_the_length_a_story_names_is_used_when_none_is_chosen():
    assert story_length_s("A stylish, 20-second lifestyle commercial celebrating artists") == 20
    assert story_length_s("a 30s ad for my mug") == 30 and story_length_s("A 12 sec TikTok") == 12
    for no in ("0-5s: she walks. 5-10s: she sits.", "after 10 seconds she smiles", "she waits 20 seconds",
               "a 90-second film", "A 2 s shot of the logo"):  # fmt: skip
        assert story_length_s(no) is None, no


def test_a_fast_story_with_its_length_in_the_text_gets_the_fast_number_of_shots(client, session_id, photo_bytes):
    brief = {**BRIEF, "story": HOODIE}
    brief.pop("video_length_s", None)
    job = create_job(client, session_id, photo_bytes, brief=brief).json()
    assert job["brief"]["video_length_s"] == 20  # from "a stylish, 20-second ... commercial"
    assert target_scenes(Brief(**job["brief"]), 2.0) == 7


def test_a_montage_packed_into_one_written_scene_is_found():
    board = _board(3)
    board.scenes[1].description = "A fast-paced creation montage: paint on hands, quick brush strokes."
    board.scenes[2].motion_prompt = "0-1 s: rapid cuts between the alley and the bridge."
    assert packed_scenes(board) == [2, 3]
    assert packed_scenes(board, beats=[object()]) == []  # the user's own beats are theirs
    assert packed_scenes(_board(3)) == []


def test_a_fast_paced_story_gets_more_shots_and_clean_cuts():
    assert fast_story(HOODIE) and fast_story("quick cuts between places") and not fast_story("a slow walk")
    assert scenes_for_length(20, 2.0) == 5 and scenes_for_length(20, 2.0, fast=True) == 7
    board = _board(4)
    plan_joins(board, Brief(**{**BRIEF, "story": HOODIE}))
    assert [s.join for s in board.scenes] == ["flow", "cut", "cut", "cut"]
    board = _board(4)  # without "fast" the shots flow on
    plan_joins(board, Brief(**{**BRIEF, "story": "A slow walk through a park."}))
    assert [s.join for s in board.scenes] == ["flow"] * 4


def test_auto_flows_on_but_cuts_where_the_person_or_place_changes():
    board = _with_cards(_board(4), [["P1"], ["P1", "product"], ["P2"], ["P2"]], ["", "", "", "a gym"])
    plan_joins(board, Brief(**BRIEF))
    assert [s.join for s in board.scenes] == ["flow", "flow", "cut", "cut"]
    assert board.continuity == "continuous"
    # A cut gets its own picture: never chained from the frame before, and the clip before it does
    # not end on it (one person never morphs into another).
    assert not is_chained(board, 2, board.scenes[2]) and is_chained(board, 1, board.scenes[1])
    board.scenes[2].image_source = "upload"
    assert not ends_on_next_picture(board, 2, board.scenes[2])


@pytest.mark.parametrize(("mode", "joins", "continuity"), [
    ("cuts", ["flow", "cut", "cut"], "continuous"),
    ("separate", ["flow", "cut", "cut"], "separate"),
    ("flowing", ["flow", "flow", "flow"], "continuous"),
])  # fmt: skip
def test_how_its_cut_sets_every_join(mode, joins, continuity):
    board = _board(3)
    board.scenes[1].join = "cut"  # a cut the story asked for: "flowing" makes it one take
    plan_joins(board, Brief(**{**BRIEF, "cutting": mode}))
    assert [s.join for s in board.scenes] == joins and board.continuity == continuity


def test_the_end_card_is_free_and_never_filmed():
    s = make_settings()
    board = _board(3)
    images, video = estimate_board_usd(s, board, voice="none")
    board.scenes[2].kind = "card"
    plan_joins(board, Brief(**BRIEF))
    images2, video2 = estimate_board_usd(s, board, voice="none")
    assert board.scenes[2].join == "cut" and video2 < video and images2 <= images


def test_one_spoken_line_runs_over_its_parts_quick_cuts():
    board = _board(4)
    for sc, part, line in zip(board.scenes, [1, 2, 2, 3], ["", "A long line over the cuts.", "", ""], strict=True):
        sc.part, sc.voiceover, sc.duration_s = part, line, 2
    assert voice_rooms(board.scenes) == [2.0, 4.0, 2.0, 2.0]


# --- compose: no frame held for a line that has room; the story's end card ---------------------------
def test_compose_lets_a_line_run_over_the_next_quick_cut_without_holding_the_frame(tmp_path):
    wav = tmp_path / "v.wav"
    clip = MockVoice().synthesize(VoiceRequest(model="m", text="word " * 6, voice="marin"))
    wav.write_bytes(clip.wav)
    voiced = C.SceneInput(clip=MOCK_CLIP, length_s=1.0, voiceover="x", voice=wav, voice_s=clip.duration_s)
    quiet = C.SceneInput(clip=MOCK_CLIP, length_s=1.0 + clip.duration_s)
    spec = C.ComposeSpec(scenes=[voiced, quiet], master_ratio="9:16", platform="tiktok", cta_text="Shop")
    held = C.plan_timeline(spec)[0].duration
    voiced.voice_room_s = 1.0 + quiet.length_s
    assert held > 1.0 and C.plan_timeline(spec)[0].duration == 1.0


def test_end_card_runs_as_long_as_its_spoken_line(tmp_path):
    wav = tmp_path / "v.wav"
    clip = MockVoice().synthesize(VoiceRequest(model="m", text="word " * 12, voice="marin"))
    wav.write_bytes(clip.wav)
    spec = C.ComposeSpec(scenes=[], master_ratio="9:16", platform="tiktok", cta_text="Shop", end_card_s=2.0)
    assert C.end_card_seconds(spec) == 2.0
    spec.end_card_voice, spec.end_card_voice_s = wav, clip.duration_s
    assert C.end_card_seconds(spec) >= 2.0


# --- clip text: only what the camera films --------------------------------------------------------------
def test_spoken_words_and_sounds_stay_out_of_the_clip_text():
    text = (
        '0:04-0:10 Chalk clapping off hands; a calm voiceover says: "Nobody claps at dawn." '
        "audio: a deep bass thud. She smiles, accompanied by a deep bass thud."
    )
    assert film_only(text) == "0:04-0:10 Chalk clapping off hands. She smiles."
    assert film_only("She walks in the rain.") == "She walks in the rain."


def test_negatives_lose_their_no_and_cut_lines_end_on_a_clause():
    sheet = AdStructure(scenes=[SceneCard()]).sheet
    sheet.never = Slot(value="no bright daytime, no staged smiles; never any text")
    assert negative_prompt(sheet).endswith(", bright daytime, staged smiles, text")
    cut = _clause_cut("handheld push continues, rain spatters and droplets fling outward under a cool key", 60)
    assert cut == "handheld push continues, rain spatters and droplets fling"  # whole words, no "under."


def test_a_guessed_action_says_who_does_it():
    ad = AdStructure(sheet={"people": [Person(id="P2", label="the sprinter")]}, scenes=[SceneCard()])
    card = SceneCard(who=CastRefs(ids=["P2", "product"]))
    assert _with_subject("sprints through puddles", card, ad.sheet) == "P2 (the sprinter) sprints through puddles"
    assert _with_subject("P2 sprints", card, ad.sheet) == "P2 sprints"


def test_brand_placeholders_become_the_product_name():
    scenes = [{"voiceover": "Own the dawn. [Brand Name].", "on_screen_text": "[product]"}]
    assert fill_placeholders(scenes, "Grip Socks Pro")
    assert scenes == [{"voiceover": "Own the dawn. Grip Socks Pro.", "on_screen_text": "Grip Socks Pro"}]


# --- "from your story", the name check, questions, claims -----------------------------------------------
def test_from_your_story_needs_most_of_its_words_in_the_story():
    story = content_words("Close-up of a runner lacing up shoes in the dark, gritty film look, anamorphic lens.")
    guess = SlotOut(value="young adult male, short dark hair, stubble, athletic build", from_story=True)
    told = SlotOut(value="gritty film look, anamorphic lens", from_story=True)
    assert _slot(guess, "", story).source == "ai_guess" and _slot(told, "", story).source == "story"


def test_the_name_check_ignores_time_stamps_brackets_and_placeholders():
    story = '[0:11-0:16] Dynamic tracking shot in Shibuya. [0:16-0:20] Hard cut; "Own it. [Brand Name]." at 5 AM'
    assert named_in_story(story, "APEX Gear") == ["Shibuya"]


def test_a_vague_idea_with_a_guessed_cast_gets_questions_from_code():
    ad = AdStructure(
        sheet={"people": [Person(id="P1", label="early-morning runner", look=Slot(value="late 20s"))]},
        scenes=[SceneCard(who=CastRefs(ids=["P1"]))],
    )
    assert open_questions(ad) == []  # the slot filler asked nothing; not called vague: nothing
    qs = open_questions(ad, vague=True)
    assert [q.slot for q in qs] == ["who", "product_moment"]
    assert qs[0].options[0] == "early-morning runner" and 2 <= len(qs[0].options) <= 4
    assert [q.slot for q in code_questions(ad)] == ["who", "product_moment"]


def test_superlatives_the_brief_does_not_make_are_flagged():
    board = _board(1)
    board.scenes[0].voiceover_ideas = ["Unbeatable traction on wet roads.", "Traction that never quits."]
    reasons = [f.reason for f in flag_testimonials(board, Brief(**BRIEF))]
    assert len(reasons) == 2 and all("superlative" in r for r in reasons)


# --- the whole flow on mock ---------------------------------------------------------------------------
def test_a_story_with_quick_cuts_and_a_logo_ending_renders_one_clip_per_shot_and_no_clip_for_the_card(
    client, ctx, session_id, photo_bytes
):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": SPORT, "video_length_s": 16}).json()
    scenes = job["storyboard"]["scenes"]
    assert len(scenes) == 6 and [s["part"] for s in scenes] == [1, 2, 2, 2, 3, 4]
    assert [s["join"] for s in scenes[1:4]] == ["cut"] * 3 and scenes[-1]["kind"] == "card"
    assert job["clips"][-1]["chars"] == 0 and all(c["chars"] <= 2310 for c in job["clips"])
    assert "Nobody claps" not in job["clips"][1]["text"]  # the spoken line is the voiceover, not the video's
    assert job.get("length_line") is None  # 14 s of shots + the story's own 2 s end card = 16 s, as picked
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    assert done["status"] == "done", done.get("last_error")
    kinds = [r.kind for r in ctx.media.submits]
    assert kinds.count("video") == 5  # six shots, the end card is drawn by us
    assert done["variants"][0]["duration_s"] == pytest.approx(16, abs=0.5)
    # The runner's first picture goes with each later picture of her (strategy plan A4).
    pictures = [r for r in ctx.media.submits if r.kind == "image"]
    assert not pictures[0].extra_images and any(len(r.extra_images) == 1 for r in pictures[1:])
    assert all("Reference photo 2 shows P1" in r.arguments["prompt"] for r in pictures if r.extra_images)


# --- the same person in every shot, and no collage after a cut (owner's hoodie test, 27 Nov 2026) ----
def test_a_picture_after_a_cut_never_gets_the_shot_befores_moment():
    from app.services.image_gen import plan_scene_image
    from app.services.providers.media import InputImage

    photo = InputImage(data=b"x", content_type="image/jpeg")
    sc = Scene(role="demo", description="On a bridge at dawn", image_prompt="P1 on a bridge", motion_prompt="",
               starts="a hand brushes the sleeve in the alley")  # fmt: skip
    kw = dict(model="m", aspect_ratio="9:16", seed=1, product=photo, product_sha256="a", keep_same="same jacket")
    flowing = plan_scene_image(scene=sc, **kw).request.arguments["prompt"]
    cut = plan_scene_image(scene=sc.model_copy(update={"join": "cut"}), **kw).request.arguments["prompt"]
    assert "First moment of the shot: a hand brushes" in flowing
    assert "First moment" not in cut and "Same in every scene: same jacket" in cut


def test_the_first_picture_of_a_person_is_sent_with_their_later_shots():
    from app.services.image_gen import cast_line, plan_scene_image
    from app.services.providers.media import InputImage

    photo, face = InputImage(data=b"x", content_type="image/jpeg"), InputImage(data=b"f", content_type="image/jpeg")
    sc = Scene(role="demo", description="P1 paints", image_prompt="P1 paints in the studio", motion_prompt="")
    kw = dict(model="m", aspect_ratio="9:16", seed=1, product=photo, product_sha256="a")
    alone = plan_scene_image(scene=sc, **kw)
    plan = plan_scene_image(
        scene=sc, cast="P1 (the creator): short dark hair", people=[("P1 (the creator)", face, "f1")], **kw
    )
    prompt = plan.request.arguments["prompt"]
    assert plan.request.extra_images == [face] and alone.request.extra_images == []
    assert "People in this shot: P1 (the creator): short dark hair" in prompt
    assert "Reference photo 2 shows P1 (the creator): keep exactly the same person" in prompt
    assert plan.cache_key != plan_scene_image(scene=sc, cast="P1 (the creator): short dark hair", **kw).cache_key

    people = [Person(id="P1", label="the creator", look=Slot(value="short dark hair, light stubble"),
                     clothes=Slot(value="the hoodie, black jeans"))]  # fmt: skip
    ad = AdStructure(sheet={"people": people}, scenes=[SceneCard(who=CastRefs(ids=["P1", "product"]))])
    assert (
        cast_line(ad.scenes[0], ad.sheet)
        == "P1 (the creator): short dark hair, light stubble; wears the hoodie, black jeans"
    )
    assert cast_line(None, ad.sheet) == ""


def test_the_continuity_check_is_told_which_shots_open_on_a_cut():
    from app.services.continuity import build_prompt

    board = _board(3)
    board.scenes[2].join = "cut"
    prompt = build_prompt(board, Brief(**BRIEF))
    assert prompt.count('"opens": "cut"') == 1 and prompt.count('"opens": "flows on"') == 2


def test_a_face_in_the_product_photo_is_the_reference_and_no_other_picture_is_sent(
    client, ctx, session_id, photo_bytes, monkeypatch
):
    # Strategy plan A4: the photo shows a woman wearing the hoodie, face visible.
    from app.services.providers import llm as mock_llm

    def with_face(brief: dict) -> dict:
        return {**mock_llm.mock_analysis(brief), "people_in_photo": True, "face_visible": True,
                "person_look": "woman in her late 20s, long dark hair"}  # fmt: skip

    monkeypatch.setitem(mock_llm.MOCK_TASKS, "analyze", with_face)
    story = "She walks out of a café onto a cobbled street. She stops at a corner. She points at the print."
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": story}).json()
    asked = [q["slot"] for q in job.get("questions") or []]
    assert "who" not in asked, asked  # the photo already shows who is in the ad
    if job["storyboard"] is None:
        job = client.post(f"/jobs/{job['id']}/answers", json={"skip": True}, headers=_h(session_id)).json()
    p1 = AdStructure.model_validate(job["storyboard"]["structure"]).sheet.people[0]
    assert p1.in_photo and p1.look.source == "photo" and "long dark hair" in p1.look.value
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    assert done["status"] == "done", done.get("last_error")
    pictures = [r for r in ctx.media.submits if r.kind == "image"]
    assert pictures and all(not r.extra_images for r in pictures)  # the photo itself is her reference
    assert all("Reference photo 1 also shows P1" in r.arguments["prompt"] for r in pictures)
