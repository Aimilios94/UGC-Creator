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
- Checked now (phase 3): the fixed rules and the projected cost (phase 1); the scene count and
  lengths of every fixture through the mock writer, and each scene's text as the splitter read it
  (phase 2); through the mock slot filler, every key slot filled or marked as the AI's guess, the
  user's words kept, the product slot's source and words, the cost shown, and the real-length line
  with its two buttons (phase 3). The 8 prompt shapes of the setup note are in
  `../prompt_shapes.json` (`tests/test_scene_splitter.py`).
- 01-06 come from the 21 Nov 2026 review (product names and photos changed to the owner's test
  photos); 07 tests the A4 rule (the person in the photo is the reference).
