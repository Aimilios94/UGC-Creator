# Golden tests v2

Test prompts from the prompt-to-ad strategy plan (`docs/plan/prompt-to-ad-strategy-plan.md`, D31).
`tests/test_golden_v2.py` loads them.

- `runs_in: ci` uses the mock writer and runs on every commit. It checks only structure, counts,
  cost and fixed wording.
- `runs_in: live` uses the real writer (gpt-5-mini, a few calls under 0.01 EUR each). It runs by
  hand, with the owner's go, before each phase ships. The `live_review` lines are checked by a person.
- `photo` names the test picture. In CI a simple picture is made in code (the repo is public). For
  live and paid runs the owner's real photos are used from `local-handoff/photos/` (local only,
  never committed): the City Harmony hoodie alone, the same hoodie worn by a woman (face visible),
  and the green Hoca Cai mug held by a hand (a person visible, no face).
- `max_clip_prompt_chars` is 2310, the plan's budget total, not Kling's 2,500 limit.
- `max_projected_cost` names the setting it is checked against: the per-ad safety cap
  (`job_cost_cap_eur`, 5 EUR). Quality first: cost never cuts a scene, action or picture.
- `phase` (when set) is the plan's build phase that makes the whole fixture checkable.
- Every key in `expect` is an assertion. The test maps each key to the phase that can check it;
  keys the code cannot check yet are reported as skipped with their phase, never deleted. A new
  key with no phase fails the test, so nothing is dropped silently.
- Phase 6 (27 Nov 2026), every key now checked: 02 with no photo (the route `video_no_photo`; the
  first starting picture made from the brief's words and each later one made from that first
  picture or continuing the clip before, so `text_to_image_or_continue` allows `text_to_image`,
  `first_picture`, `continue` and `card`; the plain note "Add a photo…"), and 07's character
  reference (in CI the photo reader's flags come from the photo's name; the face in the photo is
  the reference, no extra picture). A live read of the real photos is still to do.
- Checked before phase 6: the fixed rules and the projected cost (phase 1); the scene count and
  lengths of every fixture through the mock writer, and each scene's text as the splitter read it
  (phase 2); through the mock slot filler, every key slot filled or marked as the AI's guess, the
  user's words kept, the product slot's source and words, the cost shown, and the real-length line
  with its two buttons (phase 3); through the mock slot filler, writer and continuity check, every
  clip within 2,310 characters, each scene's own text word for word in its clip, the clip lengths,
  and 05's one-take wording with no "cut" (phase 4). Through the mock slot filler, 01's questions:
  1-2 kept by code, 2-4 buttons each, "Let the AI decide" (phase 5). 03 (the A1 swap) is live only
  (it passed live on 22 Nov 2026 after weak spots were found in code); the mock swap is tested in
  `tests/test_clip_builder.py`. The 8 prompt shapes of the setup note are in
  `../prompt_shapes.json` (`tests/test_scene_splitter.py`).
- 01-06 come from the 21 Nov 2026 review (product names and photos changed to the owner's test
  photos); 07 tests the A4 rule (the person in the photo is the reference).
