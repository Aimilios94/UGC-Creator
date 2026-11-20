"""The storyboard rule against invented testimonials (plan §8 step 2; guardrail test, M2).

A storyboard contains no first-person use or results claims unless the brief supplies them:
the code check flags them, the pipeline rewrites the storyboard once, lines still flagged
are shown for editing, and Approve is refused until they are gone.
"""

from __future__ import annotations

import copy

import pytest
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.models import Brief, Storyboard
from app.services.providers.llm import LlmHandle, build_llm, mock_storyboard
from app.services.storyboard_checks import claim_reason, flag_testimonials
from conftest import BRIEF
from helpers import approve, create_job


@pytest.mark.parametrize(
    "line",
    [
        "I've used these for 3 months and never slipped.",
        "I've been wearing them every match.",
        "I tried every sock out there.",
        "Honestly, I love how they grip.",
        "I'm obsessed with these.",
        "It changed my game.",
        "My feet feel so much better.",
        "My skin cleared up.",
        "They work for me.",
        "After two weeks, no more blisters.",
        "Players love them.",
        "Rated 5 stars by 10,000 players.",
        '"Best socks ever" - Sam',
        "The #1 grip sock.",
        "Clinically proven comfort.",
    ],
)
def test_claims_are_flagged(line):
    assert claim_reason(line) is not None


@pytest.mark.parametrize(
    "line",
    [
        "Stop scrolling: this is Grip Socks Pro.",
        "Here is how it works, in one step.",
        "Let me show you how it works.",
        "We use recycled cotton.",
        "POV: you finally found grip socks that stay put.",
        "Get yours today. 10% off with code KICK10",
        "Tired of sliding in your boots?",
        "3 reasons to switch",
    ],
)
def test_plain_lines_pass(line):
    assert claim_reason(line) is None


def _board(**voiceovers) -> Storyboard:
    data = mock_storyboard(BRIEF)
    for idx, text in voiceovers.items():
        data["scenes"][int(idx[1:])]["voiceover"] = text
    return Storyboard.model_validate(data)


def test_the_mock_storyboard_is_clean():
    assert flag_testimonials(_board(), Brief.model_validate(BRIEF)) == []


def test_a_claim_the_brief_supplies_is_allowed_and_an_invented_one_is_not():
    supplied = {**BRIEF, "description": BRIEF["description"] + " Our tester said: I've worn them for 3 months."}
    board = _board(s1="I've worn them for 3 months.")
    assert flag_testimonials(board, Brief.model_validate(BRIEF))  # not in the brief: flagged
    assert flag_testimonials(board, Brief.model_validate(supplied)) == []  # stated in the brief
    # The same claim with a figure the brief does not have is invented.
    longer = _board(s1="I've worn them for 6 months.")
    assert [f.field for f in flag_testimonials(longer, Brief.model_validate(supplied))] == ["scenes.1.voiceover"]


def test_every_spoken_and_shown_field_is_checked():
    data = mock_storyboard(BRIEF)
    data["title"] = "Customers love it"
    data["cta_text"] = "Join 10k happy players"
    data["hooks"][0]["text"] = "I tried everything"
    data["scenes"][2]["on_screen_text"] = "5 stars"
    data["scenes"][0]["description"] = "A player who has worn them for a year"
    fields = {f.field for f in flag_testimonials(Storyboard.model_validate(data), Brief.model_validate(BRIEF))}
    assert fields == {"title", "cta_text", "hooks.0.text", "scenes.2.on_screen_text", "scenes.0.description"}


# --- through the pipeline ---------------------------------------------------------------
def _scripted_storyboards(ctx, boards: list[dict], prompts: list[str]):
    """Storyboard LLM that returns the given boards in turn and records each prompt."""
    queue = list(boards)

    def respond(messages, info: AgentInfo) -> ModelResponse:
        prompts.append("\n".join(str(getattr(p, "content", "")) for m in messages for p in getattr(m, "parts", [])))
        board = queue.pop(0) if len(queue) > 1 else queue[0]
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=board)])

    handle = LlmHandle(
        model=FunctionModel(respond, model_name="scripted"), provider="mock", model_name="mock", settings={}
    )
    ctx.llm_factory = lambda task: handle if task == "storyboard" else build_llm(ctx.settings, task)


def _bad_board() -> dict:
    data = copy.deepcopy(mock_storyboard(BRIEF))
    data["scenes"][1]["voiceover"] = "I've used these for 3 months and never slipped."
    return data


def _storyboard_calls(ctx, job_id) -> int:
    with ctx.db.tx() as c:
        return c.execute(
            """select count(*) as n from llm_calls l join stage_runs s on s.id = l.stage_run_id
               where l.job_id = %s and s.stage = 'storyboard' and l.status = 'billed'""",
            (job_id,),
        ).fetchone()["n"]


def test_a_flagged_storyboard_is_rewritten_once_with_the_lines_as_feedback(client, ctx, session_id, photo_bytes):
    prompts: list[str] = []
    _scripted_storyboards(ctx, [_bad_board(), mock_storyboard(BRIEF)], prompts)
    job = create_job(client, session_id, photo_bytes).json()
    assert job["status"] == "draft" and job["flags"] == []
    assert "I've used these" not in job["storyboard"]["scenes"][1]["voiceover"]
    assert len(prompts) == 2 and "scenes.1.voiceover" in prompts[1] and "testimonial rule" in prompts[1]
    assert _storyboard_calls(ctx, job["id"]) == 2  # both calls are paid and counted
    assert approve(client, session_id, job["id"]).status_code == 202


def test_lines_still_flagged_block_approval_until_edited(client, ctx, session_id, photo_bytes):
    """Guardrail (M2): no approved storyboard contains a first-person use or results claim
    that the brief does not supply."""
    prompts: list[str] = []
    _scripted_storyboards(ctx, [_bad_board()], prompts)
    job = create_job(client, session_id, photo_bytes).json()
    assert len(prompts) == 2  # rewritten once, then left to the user
    assert [f["field"] for f in job["flags"]] == ["scenes.1.voiceover"]

    r = approve(client, session_id, job["id"])
    assert r.status_code == 409 and "flagged" in r.json()["detail"]
    with ctx.db.tx() as c:
        assert c.execute("select status from jobs where id = %s", (job["id"],)).fetchone()["status"] == "draft"

    board = job["storyboard"]
    board["scenes"][1]["voiceover"] = "Grip that keeps your foot locked in the boot."
    h = {"X-Session-Id": session_id}
    edited = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=h).json()
    assert edited["flags"] == []
    assert approve(client, session_id, job["id"]).status_code == 202


def test_a_claim_supplied_by_the_brief_is_not_rewritten(client, ctx, session_id, photo_bytes):
    brief = {**BRIEF, "description": BRIEF["description"] + " I've used these for 3 months and never slipped."}
    prompts: list[str] = []
    _scripted_storyboards(ctx, [_bad_board()], prompts)
    job = create_job(client, session_id, photo_bytes, brief=brief).json()
    assert len(prompts) == 1 and job["flags"] == []
    assert approve(client, session_id, job["id"]).status_code == 202


def test_a_failed_rewrite_keeps_the_first_storyboard_for_editing(client, ctx, session_id, photo_bytes):
    calls = {"n": 0}

    def respond(messages, info: AgentInfo) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("provider timeout")
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=_bad_board())])

    handle = LlmHandle(
        model=FunctionModel(respond, model_name="flaky"), provider="mock", model_name="mock", settings={}
    )
    ctx.llm_factory = lambda task: handle if task == "storyboard" else build_llm(ctx.settings, task)
    job = create_job(client, session_id, photo_bytes).json()
    assert job["last_error"] is None and job["storyboard"] is not None
    assert [f["field"] for f in job["flags"]] == ["scenes.1.voiceover"]
    assert {s["stage"]: s["status"] for s in job["stages"]}["storyboard"] == "done"
