"""A story's own structure (1-5 scenes), the ad's sound (voice, no voice, any music track),
and the voice and music lists with previews (D28)."""

from __future__ import annotations

from types import SimpleNamespace

from app import worker
from app.services.music import music_for
from conftest import BRIEF, new_session
from helpers import approve, create_job, make_video, to_video

FOUR_BEATS = (
    "0:00 - 0:02 (Establish): handheld shot follows a man crossing a wet zebra crossing at night in the hoodie.\n"
    "0:02 - 0:04 (Spark): he cups his hands against the rain; neon glows in the mist.\n"
    "0:04 - 0:06 (Walk): slow steps over a dark puddle, ripples reflecting the city lights.\n"
    '0:06 - 0:08 (Close): slow push-in on the back print, neon bokeh. "Wear the night."'
)


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


def test_a_story_with_four_beats_makes_a_four_scene_ad(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": FOUR_BEATS}).json()
    scenes = job["storyboard"]["scenes"]
    assert [s["role"] for s in scenes] == ["hook", "demo", "demo", "cta"]
    assert [s["duration_s"] for s in scenes] == [2, 2, 2, 2]
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    assert done["status"] == "done"
    assert [r.kind for r in ctx.media.submits] == ["image"] * 4 + ["video"] * 4
    counts = {k: sum(a["kind"] == k for a in done["assets"]) for k in ("still", "carousel")}
    assert counts == {"still": 4, "carousel": 5}


def test_scenes_can_be_added_and_removed_before_approval_only(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    extra = {**board["scenes"][1], "description": "A close-up of the stitching.", "image_prompt": ""}
    board["scenes"] = [*board["scenes"][:2], extra, extra, board["scenes"][2]]
    view = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=_h(session_id)).json()
    assert [s["role"] for s in view["storyboard"]["scenes"]] == ["hook", "demo", "demo", "demo", "cta"]
    six = {**board, "scenes": [*board["scenes"], extra]}
    assert client.put(f"/jobs/{job['id']}/storyboard", json=six, headers=_h(session_id)).status_code == 422
    empty = {**board, "scenes": [{**extra, "description": "", "image_prompt": ""}]}
    assert client.put(f"/jobs/{job['id']}/storyboard", json=empty, headers=_h(session_id)).status_code == 422
    one = {**board, "scenes": [board["scenes"][0]]}
    view = client.put(f"/jobs/{job['id']}/storyboard", json=one, headers=_h(session_id)).json()
    assert [s["role"] for s in view["storyboard"]["scenes"]] == ["cta"]

    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    images_done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    more = {**images_done["storyboard"], "scenes": images_done["storyboard"]["scenes"] * 2}
    r = make_video(client, session_id, job["id"], more)
    assert r.status_code == 422 and "fixed" in r.json()["detail"]


def test_no_voiceover_skips_the_voice_and_its_cost(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "voice": "none"}).json()
    with_voice = create_job(client, session_id, photo_bytes).json()
    assert job["estimate"]["video"]["usd"] < with_voice["estimate"]["video"]["usd"]
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    assert done["status"] == "done" and ctx.voice.requests == []
    assert all(c.get("audio_track", True) for c in done["variants"][0]["checks"])  # music still plays


def test_sound_can_change_until_the_video_is_made(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    r = client.put(f"/jobs/{job['id']}/sound", json={"voice": "onyx", "music": "tech"}, headers=_h(session_id))
    assert r.status_code == 200 and (r.json()["brief"]["voice"], r.json()["brief"]["music"]) == ("onyx", "tech")
    assert client.put(f"/jobs/{job['id']}/sound", json={"music": "polka"}, headers=_h(session_id)).status_code == 422
    assert client.put(f"/jobs/{job['id']}/sound", json={"voice": "none"}, headers=_h(new_session())).status_code == 404
    to_video(client, ctx, session_id, job["id"])
    late = client.put(f"/jobs/{job['id']}/sound", json={"voice": "marin"}, headers=_h(session_id))
    assert late.status_code == 409


def test_music_choice_picks_the_bed():
    def brief(music, theme=None):
        return SimpleNamespace(music=music, theme=theme)

    assert music_for(brief("none"), "food") is None
    assert music_for(brief("theme", "sport"), "food").name == "sport.m4a"
    assert music_for(brief("theme"), "food").name == "food.m4a"
    assert music_for(brief("tech", "sport"), "food").name == "tech.m4a"  # any track, whatever the theme


def test_voice_and_music_lists_with_previews(client):
    voices = client.get("/voices").json()
    assert [v["id"] for v in voices] == ["marin", "cedar", "coral", "onyx"]
    for v in voices:
        if v["sample"]:
            got = client.get(v["sample"])
            assert got.status_code == 200 and got.headers["content-type"].startswith("audio/")
    music = client.get("/music").json()
    assert {m["id"] for m in music} == {"sport", "beauty", "tech", "food", "fashion"}
    got = client.get(music[0]["sample"])
    assert got.status_code == 200 and got.headers["content-type"].startswith("audio/")
    assert client.get("/music/../config.m4a").status_code == 404
    assert client.get("/voices/robot.m4a").status_code == 404


def test_a_writer_that_merges_beats_is_corrected_and_the_story_sets_text_and_lengths(
    client, ctx, session_id, photo_bytes
):
    """The real writer once merged two timed beats; the app counts them itself (D28)."""
    from pydantic_ai import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    from app.services.providers.llm import LlmHandle, build_llm, mock_storyboard

    calls = []

    def respond(messages, info):
        calls.append(1)
        board = mock_storyboard({"product_name": "Hoodie"})  # 3 scenes, as if beats were merged
        if len(calls) > 1:
            board["scenes"] = board["scenes"][:2] + [dict(board["scenes"][1]), board["scenes"][2]]
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=board)])

    handle = LlmHandle(model=FunctionModel(respond), provider="mock", model_name="mock", settings={})
    ctx.llm_factory = lambda task: handle if task == "storyboard" else build_llm(ctx.settings, task)
    story = FOUR_BEATS.replace("0:06 - 0:08", "0:06 - 0:09")
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": story}).json()
    scenes = job["storyboard"]["scenes"]
    assert len(calls) == 2 and len(scenes) == 4
    assert [s["duration_s"] for s in scenes] == [2, 2, 2, 3]  # from the timestamps
    assert scenes[1]["description"].startswith("0:02 - 0:04 (Spark)")  # the user's own words


def test_a_chosen_video_length_sets_the_scenes_and_their_lengths(client, session_id, photo_bytes):
    for length, scenes_n in ((10, 3), (15, 5), (30, 5)):
        job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "video_length_s": length}).json()
        scenes = job["storyboard"]["scenes"]
        assert len(scenes) == scenes_n, length
        assert sum(s["duration_s"] for s in scenes) == min(length - 2, 10 * scenes_n)  # + the 2 s end card
        assert all(2 <= s["duration_s"] <= 10 for s in scenes)
    auto = create_job(client, session_id, photo_bytes).json()
    assert len(auto["storyboard"]["scenes"]) == 3  # no length, no story: the usual 3
    timed = create_job(client, session_id, photo_bytes, brief={**BRIEF, "video_length_s": 30, "story": FOUR_BEATS})
    assert len(timed.json()["storyboard"]["scenes"]) == 4  # the story's timestamps win
    assert create_job(client, session_id, photo_bytes, brief={**BRIEF, "video_length_s": 3}).status_code == 422


def test_spoken_lines_get_the_time_they_need():
    from app.services.scene_plan import at_least_speech, fit_lengths, speech_seconds

    long_line = "Stop scrolling: this is the hoodie everyone asks me about on the street."
    assert speech_seconds("") == 0 and speech_seconds(long_line) >= 5
    lengths = fit_lengths([long_line, "", "Get yours."], 12)
    assert sum(lengths) == 12 and lengths[0] >= speech_seconds(long_line) and min(lengths) >= 2
    assert at_least_speech([2, 5], [long_line, ""])[0] >= speech_seconds(long_line)


def test_joining_scenes_keeps_each_uploaded_picture_with_its_scene(client, session_id, photo_bytes):
    import io

    from PIL import Image

    job = create_job(client, session_id, photo_bytes).json()
    buf = io.BytesIO()
    Image.new("RGB", (400, 700), (200, 30, 30)).save(buf, "PNG")
    h = {"X-Session-Id": session_id}
    view = client.post(
        f"/jobs/{job['id']}/scenes/2/image", files={"image": ("mine.png", buf.getvalue(), "image/png")}, headers=h
    ).json()
    scenes = view["storyboard"]["scenes"]
    assert all(s["uid"] for s in scenes) and len({s["uid"] for s in scenes}) == 3
    # Join scenes 1 and 2 (as "Apply the recommendation" does): scene 3 keeps its uploaded picture.
    a, b, c = scenes
    joined = {
        **a,
        "description": a["description"] + " " + b["description"],
        "duration_s": a["duration_s"] + b["duration_s"],
    }
    view = client.put(f"/jobs/{job['id']}/storyboard", json={**view["storyboard"], "scenes": [joined, c]}, headers=h)
    assert view.status_code == 200, view.text
    kept = view.json()["storyboard"]["scenes"]
    assert [s["uid"] for s in kept] == [a["uid"], c["uid"]] and kept[1]["image_source"] == "upload"
    approve(client, session_id, job["id"])  # the upload key followed scene 3 to its new position


def test_a_joined_scene_with_long_text_can_be_saved(client, session_id, photo_bytes):
    """Joining two story beats once made the text longer than the old 800-character limit (D28)."""
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    a, b, c = board["scenes"]
    joined = {**a, "description": "x" * 990, "voiceover": "See this backprint. That print hits night light right."}
    r = client.put(
        f"/jobs/{job['id']}/storyboard", json={**board, "scenes": [joined, c]}, headers={"X-Session-Id": session_id}
    )
    assert r.status_code == 200, r.text
