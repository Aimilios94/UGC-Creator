"""Every scene flows into the next (D30): the continuity check after the writer, a clip that ends
on the next scene's own picture (Kling's end frame), chaining from the cut, and how compose joins
each cut. Mock providers only."""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageStat
from pydantic_ai import ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import repository as repo
from app import worker
from app.models import Storyboard
from app.services import compose as C
from app.services.continuity import ContinuityPlan, SceneFlow, apply_plan
from app.services.providers.llm import LlmHandle, build_llm
from app.services.providers.media import _mock_clip
from helpers import create_job, separate_shots, to_video

VISIBLE = ("description", "voiceover", "on_screen_text", "duration_s", "role")


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


def _put(client, session_id, job_id, board):
    r = client.put(f"/jobs/{job_id}/storyboard", json=board, headers=_h(session_id))
    assert r.status_code == 200, r.text
    return r.json()


def _clips(ctx):
    return [r for r in ctx.media.submits if r.kind == "video"]


def _timeline(ctx, job_id):
    with ctx.db.tx() as c:
        return c.execute("select output from variants where job_id = %s and label = 'A'", (job_id,)).fetchone()[
            "output"
        ]["timeline"]


def _image_bytes(ctx, job_id, idx):
    row = next(r for r in repo.list_scenes(ctx.db, job_id) if r["idx"] == idx)
    return ctx.storage.get(repo.get_asset(ctx.db, str(row["image_asset_id"]))["storage_key"])


# --- the continuity check ------------------------------------------------------------------------
def test_the_continuity_check_fills_only_the_hidden_instructions(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    assert board["continuity"] == "continuous"  # the default (D30)
    assert {s["stage"]: s["status"] for s in job["stages"]}["continuity"] == "done"
    assert board["keep_same"]
    scenes = board["scenes"]
    assert all(s["starts"] and s["ends"] for s in scenes)
    assert "scene 1" in scenes[1]["starts"]  # scene 2 opens on scene 1's last moment

    # The check never touches what the user reads: only starts, ends and keep_same change.
    plain = Storyboard.model_validate(
        {**board, "keep_same": "", "scenes": [{**s, "starts": "", "ends": ""} for s in scenes]}
    )
    plan = ContinuityPlan(keep_same="same", scenes=[SceneFlow(starts="a", ends="b") for _ in scenes])
    checked = apply_plan(plain, plan)
    for before, after in zip(plain.scenes, checked.scenes, strict=True):
        assert all(getattr(before, f) == getattr(after, f) for f in VISIBLE)
        assert before.motion_prompt == after.motion_prompt and before.image_prompt == after.image_prompt
    # A plan with another number of scenes is not used.
    assert apply_plan(plain, ContinuityPlan(keep_same="x", scenes=[SceneFlow(starts="a", ends="b")])) == plain


def test_a_failed_continuity_check_keeps_the_storyboard(client, ctx, session_id, photo_bytes):
    def fail(messages, info: AgentInfo) -> ModelResponse:
        raise RuntimeError("provider timeout")

    broken = LlmHandle(model=FunctionModel(fail, model_name="broken"), provider="mock", model_name="mock", settings={})
    ctx.llm_factory = lambda task: broken if task == "continuity" else build_llm(ctx.settings, task)
    job = create_job(client, session_id, photo_bytes).json()
    assert job["status"] == "draft" and job["last_error"] is None
    assert len(job["storyboard"]["scenes"]) == 3 and not any(s["starts"] for s in job["storyboard"]["scenes"])
    assert {s["stage"]: s["status"] for s in job["stages"]}["continuity"] == "failed"


def test_the_start_and_end_notes_reach_the_clips_in_a_continuous_shot_only(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    clips = _clips(ctx)
    scenes = job["storyboard"]["scenes"]
    assert scenes[1]["starts"][:40] in clips[1].arguments["prompt"]
    assert scenes[0]["ends"][:40] in clips[0].arguments["prompt"]
    assert "Same in every scene:" in clips[0].arguments["prompt"]
    image = next(r for r in ctx.media.submits if r.kind == "image")
    assert "Same in every scene:" in image.arguments["prompt"]

    other = separate_shots(client, session_id, create_job(client, session_id, photo_bytes).json())
    before = len(ctx.media.submits)
    to_video(client, ctx, session_id, other["id"])
    worker.run_once(ctx)
    new = ctx.media.submits[before:]
    assert all("Same in every scene:" not in r.arguments["prompt"] for r in new)  # separate shots: as before


# --- own pictures: the clip before ends on them ----------------------------------------------------
def test_with_a_picture_in_every_scene_each_clip_ends_on_the_next_picture(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    for s in board["scenes"]:
        s["image_source"] = "product"
    _put(client, session_id, job["id"], board)
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    clips = _clips(ctx)
    assert len(clips) == 3
    assert clips[0].tail_image.data == _image_bytes(ctx, job["id"], 1)
    assert clips[1].tail_image.data == _image_bytes(ctx, job["id"], 2)
    assert clips[2].tail_image is None  # the last scene goes to the end card
    assert "Ends exactly on the end image given" in clips[0].arguments["prompt"]
    runs = {r["scene_idx"]: r for r in repo.list_stage_runs(ctx.db, job["id"]) if r["stage"] == "video"}
    assert runs[0]["output"]["ends_on_next"] and runs[1]["output"]["ends_on_next"]
    assert [t["blend_out"] for t in _timeline(ctx, job["id"])] == [0.1, 0.1, 0.0]  # a very short blend


def test_a_mix_of_continued_scenes_and_own_pictures_connects_at_every_cut(client, ctx, session_id, photo_bytes):
    """Scene 1 generated, scene 2 continues from scene 1's cut, scene 3 is my own picture."""
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    board["scenes"][2]["image_source"] = "product"
    _put(client, session_id, job["id"], board)
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    images = {r["scene_idx"]: r["provider"] for r in repo.list_stage_runs(ctx.db, job["id"]) if r["stage"] == "image"}
    assert images == {0: "mock", 1: "chain", 2: "own"}
    clips = _clips(ctx)
    assert clips[0].tail_image is None  # scene 2 starts from scene 1's own last frame
    assert clips[1].tail_image.data == _image_bytes(ctx, job["id"], 2)
    assert [t["blend_out"] for t in _timeline(ctx, job["id"])] == [0.0, 0.1, 0.0]  # clean cut, short blend


def test_separate_shots_keep_their_own_pictures_and_the_soft_blend(client, ctx, session_id, photo_bytes):
    job = separate_shots(client, session_id, create_job(client, session_id, photo_bytes).json())
    board = job["storyboard"]
    for s in board["scenes"]:
        s["image_source"] = "product"
    _put(client, session_id, job["id"], board)
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    assert all(c.tail_image is None for c in _clips(ctx))
    assert [t["blend_out"] for t in _timeline(ctx, job["id"])] == [0.3, 0.3, 0.0]


def test_the_end_frame_reaches_fal_and_changes_the_cache_key():
    from test_storage_and_providers import FakeFal

    from app.models import Scene
    from app.services.providers.media import FalMedia, InputImage
    from app.services.video_gen import plan_scene_video

    scene = Scene(role="hook", description="d", image_prompt="i", motion_prompt="0-5 s: slow push-in.", duration_s=4)
    start = InputImage(b"start", "image/jpeg")
    end = InputImage(b"end", "image/jpeg", url="https://storage.googleapis.com/signed-end")
    common = dict(model="fal-ai/kling-video/v2.5-turbo/pro/image-to-video", scene=scene, duration_s=5, used_s=4)
    plain = plan_scene_video(**common, reference=start, reference_sha256="a", position=(0, 2), continuous=True)
    ending = plan_scene_video(
        **common, reference=start, reference_sha256="a", position=(0, 2), continuous=True, end_image=end,
        end_image_sha256="b",
    )  # fmt: skip
    assert plain.cache_key != ending.cache_key
    assert "1.2 times faster" in ending.request.arguments["prompt"]
    assert "Only the first" not in ending.request.arguments["prompt"]  # the whole clip is used, a little faster
    fake = FakeFal()
    FalMedia("k", client=fake).submit(ending.request)
    args = fake.submitted[0][1]
    assert args["tail_image_url"] == "https://storage.googleapis.com/signed-end"
    assert args["image_url"] == "https://v3.fal.media/files/fake/input.jpg"


# --- compose: the cut matches ---------------------------------------------------------------------
def _jpeg(color) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (540, 960), color)
    for x in range(0, 540, 60):  # a pattern, so a jump would show
        img.paste((255, 255, 255), (x, 0, x + 6, 960))
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _frame_diff(path, t_a, t_b, tmp):
    a = C.frame_at(path, t_a, tmp / f"a{t_a}.png").convert("L").resize((90, 160))
    b = C.frame_at(path, t_b, tmp / f"b{t_b}.png").convert("L").resize((90, 160))
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]  # mean grey-level change per pixel


def test_a_clip_that_ends_on_the_next_picture_meets_it_at_the_cut(tmp_path):
    """Scene 1's clip (5 s, played in 4 s) ends on scene 2's picture: across the cut the frames
    barely change; without the end frame, the cut jumps."""
    first, second = _jpeg((200, 40, 40)), _jpeg((30, 60, 200))
    a_end = tmp_path / "a_end.mp4"
    a_end.write_bytes(_mock_clip(first, 5, second))
    a_plain = tmp_path / "a_plain.mp4"
    a_plain.write_bytes(_mock_clip(first, 5))
    b = tmp_path / "b.mp4"
    b.write_bytes(_mock_clip(second, 5))

    def master(clip, fit, blend):
        scenes = [
            C.SceneInput(clip=clip, length_s=4.0, fit_clip=fit, blend_out_s=blend),
            C.SceneInput(clip=b, length_s=4.0),
        ]
        spec = C.ComposeSpec(
            scenes=scenes, master_ratio="9:16", platform="tiktok", cta_text="Shop now", ratios=("9:16",), scale=0.25
        )
        timeline = C.plan_timeline(spec)
        out = tmp_path / f"m_{fit}_{blend}.mp4"
        C.build_master(spec, timeline, (270, 480), out)
        return out, timeline

    joined, timeline = master(a_end, True, 0.0)
    assert timeline[0].speed > 1.2  # the whole 5 s clip in 4 s
    assert abs(C.probe_duration(joined) - 8.0) < 0.1
    jumped, _ = master(a_plain, False, 0.0)
    smooth = _frame_diff(joined, 3.95, 4.05, tmp_path)
    jump = _frame_diff(jumped, 3.95, 4.05, tmp_path)
    assert smooth < 5 and jump > 4 * smooth


def test_clean_cuts_and_blends_together_keep_the_ad_length(tmp_path):
    from app.services.providers.media import MOCK_CLIP

    scenes = [
        C.SceneInput(clip=MOCK_CLIP, length_s=2.0, blend_out_s=0.0),
        C.SceneInput(clip=MOCK_CLIP, length_s=2.0, blend_out_s=0.1),
        C.SceneInput(clip=MOCK_CLIP, length_s=2.0, blend_out_s=0.3),
        C.SceneInput(clip=MOCK_CLIP, length_s=2.0),
    ]
    spec = C.ComposeSpec(
        scenes=scenes, master_ratio="9:16", platform="tiktok", cta_text="Shop now", ratios=("9:16",), scale=0.25
    )
    result = C.compose(spec, tmp_path / "out")
    assert result.duration_s == 10.0  # 4 x 2 s + 2 s end card
    assert abs(C.probe_duration(result.exported[0].path) - 10.0) < 0.15
