# UGC Ad Builder: Prompt-to-Ad Strategy Plan

Nov 21, 2026 · @Aimilios

## Goal and core idea

Every prompt, long or short, timed or not, well or badly written, is read into **one fixed structure** before anything is written for the models. Code, not the AI, then builds each Kling and Nano Banana prompt from that structure. This gives the same quality floor whether the user types 10 words or 12,000 characters.

Three rules carry the plan:

- **Read, don't rewrite.** The user's words are stored in slots and reach Kling as they are whenever they fit.
- **Mark every guess.** Each slot is marked "yours" or "AI's guess". The user sees the guesses and can fix them in one click.
- **Plan the budget, don't check it afterwards.** Each clip has a fixed character budget per part. The aim is about 1,000–1,400 characters, with 2,500 as the hard ceiling, because short, clear prompts work better.

This closes the 7 gaps in section 5 of the current setup note (no questions, no fixed scene structure, timestamp-only detection, rewritten user words, no reusable characters, a budget that is only checked, no "what I assumed" view).

## What changed in v2 (review of 21 Nov 2026)

The review approved the plan and added 6 amendments plus a wider input scope. All are applied. Every changed or new passage below starts with **v2:**, so you can find them with a search.

| # | Change | Where |
| --- | --- | --- |
| Scope | Every input combination: photo or no photo, story or brief, video or image. A no-photo route uses text-to-image pictures; a text-only clip is a per-scene fallback | Workflow, Image path |
| A1 | Precedence: user action text goes to Kling word for word unless it hits a weak spot or has no filmable action | Writer rules, rules files |
| A2 | Fixed rules rewritten and measured: worst case exactly 300 characters (today: 458). Budget total 2,310 unchanged | Clip builder |
| A3 | v2.1: quality first. A length planner picks what each scene needs and shows the cost; the cap is only a safety limit | Workflow, UI, Decisions |
| A4 | A person already in the product photo is the character reference | Image path |
| A5 | Simulated angle changes inside one take, worded as camera moves | Writer rules, rules files |
| A6 | No-photo product wording is a variable in the clip builder | Clip builder |
| Tests | 6 new golden prompts, plus a small live set for the 2 that need the real model | Files, build order and tests |

**v2.1, owner's rule: quality first.** Cost never removes a rule, an action, a scene or a picture. Paying a bit more for a better ad is fine. Any future change that trades quality for cost needs the owner's yes first.

**v2.2 (review of v2.1, 21 Nov 2026):** costs now use the real exchange rate (1 USD ≈ 0.91 EUR), so the most expensive ad is about 3.50 EUR. The per-ad safety cap is 5 EUR, the daily cap must be at least 5 EUR, the over-cap case is defined, prices are tied to exact model IDs, and the text-to-video endpoint is confirmed.

**Where the review was adjusted (not skipped):**

- **Too ambiguous to animate** (A1) is defined tightly: there is no subject plus a visible action a camera could film. Anything else stays word for word.
- **Tests for the bad prompt and the weak-spot swap** can't be judged by the mock writer. They run as live tests on the real model (a few calls under 0.01 EUR each); CI checks only the structure.
- **No-photo ads** carry a note that the product is the AI's version of it, because the real product is never seen.
- **Length picker:** v2.1: it stays at 4–52 s. The cost is shown, never used to cut scenes.

## The workflow by name

Steps 1–8 run for every ad and turn any prompt into the structure. The router's choice then sends the job down the video path or the image path.

&#91;embedded content: prompt-to-ad workflow · 7 shared steps, 2 paths\]

**The same steps in text** (for anyone reading this without the drawing):

- **Shared, every ad:** 1 Intake (story, brief, optional photo) → 2 Photo reader (product, any person in it) → 3 Router (video or image, photo or not) → 4 Scene splitter → 5 Slot filler (cast and world sheet + scene cards) → 6 Gap check (0–3 quick questions) → 7 Writer (fills gaps, safe swaps only) → 8 Length + cost (best length per scene, cost shown).
- **Video path:** 9 Continuity → 10 Clip builder → 11 Storyboard review → 12 First pictures (photo edit or text-to-image) → 13 Voice → 14 Clips (image-to-video; text only as a fallback) → 15 Compose → 16 Export.
- **Image path:** 9 Image builder → 10 Image review → 11 Picture (photo edit or text-to-image) → 12 Compose → 13 Export.
- Nothing paid runs until the user approves the review step.

The image builder (image step 9) is also what makes the video's first pictures (video step 12), so both paths share one picture recipe.

**v2: the router reads two things, the ad kind and whether there is a product photo.** Every combination ends in the same sheet and scene cards.

| The user gives | Path |
| --- | --- |
| Photo + story | Nano Banana edits the photo for each scene picture, then image-to-video |
| Photo only | The writer builds hook, demo and call to action from the brief |
| Story, no photo | Scene pictures from Nano Banana text-to-image, using the cast sheet; then image-to-video. The product slot comes from the name, brief and answers. If its look is unclear, ask "What does your product look like?" |
| Brief only (short or no story) | Full AI with up to 3 quick questions |
| Image ad, with story | Image path, one card per picture |
| Image ad, photo, no story | The writer makes 1–5 cards from the brief; no clips |

**Rule for every path:** a first picture, then image-to-video. This is the strongest setup for consistency, with end frames and Continue chains. Kling text-to-video (no start picture) is only a per-scene fallback, chosen in the scene's picture menu as "No picture, text only", with a small note that the look may change between scenes. Photo-first stays the default.

**v2: step 8, the length and cost planner** (today's `scene_plan.py`), now runs in the shared start for video ads; it does nothing for image ads. It gives each scene the length its action needs and shows the cost (v2.1, see Decisions).

## The structure: one sheet, one card per scene

Every ad is stored as one **cast and world sheet** plus 1–5 **scene cards**. Every slot holds a value and its source: `user` (typed), `photo` (from the photo reader), `answer` (from a quick question) or `ai_guess`. Only `ai_guess` slots may be changed by the AI later.

**Cast and world sheet** (written once, reused in every clip; these are the video's "anchors")

| Entry | What it holds | Example |
| --- | --- | --- |
| Product | Exact look from the photo reader, plus details not visible in the photo. v2: with no photo, from the product name, brief and answers (source user or answer) | black hoodie, white chest logo, logo also on the back |
| People (one entry each, with an id) | Face, hair, age range, clothes, and details off-camera or on the hidden side | P1: man, late 20s, short dark hair, wears the hoodie, grey joggers |
| Place | Where it happens | wet city street at night, neon shop signs |
| Time and light | Time of day, light source, mood | night, neon and street lamps, soft rain |
| Look | Style (realistic, cinematic, 3D, 2D), lens, colour grade | realistic, 35 mm, cool blue grade |
| Camera style | How the whole ad is filmed | handheld phone, UGC feel |
| Never | Things to avoid in every clip | no other people, no text |

**Scene card** (one per scene)

| Slot | What it holds | Key slot? | Used by |
| --- | --- | --- | --- |
| Who | Cast ids in the shot (P1, product) | yes | video, image |
| Action | One main action, in simple verbs | yes | video, image (as a pose) |
| Camera | Shot size, move, speed (static, push in, pan, handheld) | no | video, image (shot size, angle) |
| Timeline | 2–4 time marks for a 5 s clip, up to 5 for 10 s | no | video |
| Start | The first moment of the shot | no | video |
| End | The last moment; for the last scene, how the ad ends | yes (last scene) | video |
| Product moment | How the product is shown (worn, held, close-up, in use) | yes | video, image |
| Place or light change | Only if this scene differs from the sheet | no | video, image |
| Spoken line | The voiceover, word for word | no | video |
| Headline | On-screen words, drawn by us in compose | no | video, image |
| Avoid | Negatives for this scene only | no | video, image |
| Length | 2–10 s | no | video |

Ad-level fields stay as today (goal, hook, offer, button, platform, shape), plus **kind: video or image**, which the router reads.

## Scene splitter: any prompt shape becomes scenes

Code tries each shape in this order and stops at the first that matches. The AI is used only for the last two.

1. **Time ranges** (`0:00 – 0:04`): keep today's `story_beats.py` rules as they are.
2. **"Scene N" or "Shot N" headings**, 2 or more: each heading starts a scene. Seconds are taken from the text if given ("3 s", "3 seconds"), otherwise from the length plan.
3. **Numbered or bulleted list**, 2–5 items, where each item has an action: each item is a scene.
4. **Paragraphs**, 2–5, no time ranges: the AI marks each one "scene" or "notes" (or groups several into one scene) inside the slot filler call it already makes, so this costs nothing extra. A simple rule can't do this: the owner's own prompt opens with 5 paragraphs of notes. Code then checks 1–5 scenes, every paragraph used once and word for word, and notes kept whole; if the check fails, it asks once more. The storyboard shows "We found 3 scenes and 2 notes", and the user can move a paragraph or merge scenes there.
5. **No shape found**: the text stays as one block. The scene count comes from the chosen length, or 3 (hook, demo, call to action) on Auto. The slot filler spreads the content across the scenes.

Rules for every shape:

- Text that is not a scene (characters, style, place, rules, headings) goes into the **cast and world sheet**, never dropped.
- More than 5 scenes: merge the shortest neighbours (today's rule), and **show the user** "Scenes 4 and 5 were joined". No silent cuts.
- "Cut to…" inside a scene starts a new scene if there is room (under 5). If not, it becomes a bridging move (whip pan, match on action) between two scenes. A cut is never put inside one Kling clip.
- Output: a list of beats, each with its raw text (kept word for word), seconds if given, and the leftover notes.

## Gap check and quick questions

Questions appear automatically **only when a key slot is empty**, at most 3, and the user can always skip them. A detailed, timed prompt usually gets zero.

**Key slots, in priority order** (when more than 3 are empty, ask about the first 3):

1. **Who is in it?** (no person or hands in the sheet, and the product needs someone to use it)
2. **How is the product shown?** (product moment empty in most scenes)
3. **Where does it happen?** (place empty)
4. **How should it end?** (last scene's end empty)

**v2:** with no product photo, **"What does your product look like?"** goes first whenever the product slot can't describe its look (colour, shape, material). It counts toward the 3.

**How a question looks**

- One short line, 2–4 suggestion buttons made from the brief and the photo (for example "Young woman at home", "Man on a city street", "Only hands"), a free-text box, and **"Let the AI decide"** (the default).
- All questions on one screen, with a **"Skip all"** button. Skipping keeps the AI's guesses, marked as such.
- Answers are saved with source `answer` and never changed by the AI.

**Cost:** no extra AI call. The slot filler returns the questions and the suggestion buttons in the same call that fills the structure.

Any guesses left are marked lightly inside each scene as "AI's guess". The user can change them there, or leave them (see UI).

## Writer rules: fill the gaps, never rewrite

The writer gets the filled structure and returns **only the empty slots**, plus the title, 3 hooks and the button text. It never writes the final Kling text; code does (next section).

- **User slots are locked.** After the writer runs, code compares every `user` and `answer` slot with its value before. Any change is put back, and the change is logged.
- **One main action per clip**, in plain verbs: "walks toward the camera, stops, lifts the mug to her face".
- **Spoken lines word for word.** Code checks the length: at most about 2.5 words per second of scene. A line that is too long gets a warning with "make the scene longer"; it is never cut.
- **No invented testimonials** (today's check stays).
- **No cuts inside a clip** (see the scene splitter).

**v2: precedence rule (A1).** The user's action text goes to Kling word for word, **unless** one of these two is true:

1. It hits a Kling weak spot from the table below.
2. It has no filmable action: no subject plus a visible action a camera could film (for example "walks with cool energy" has a subject and "walks", so it stays; "pure vibes, unstoppable" has neither, so it is swapped).

In those two cases only, the writer swaps it for a safe version, keeps the intent, marks it "AI changed: \[reason\]" on the scene card, and Undo is available. Spoken lines, headlines and descriptions are never rewritten. When in doubt, keep the user's words.

**v2: angle changes inside one take (A5).** The timeline slot may describe a simulated angle change inside one continuous take. It is worded as a camera move, never "cut to", for example: "0–2 s: full-body shot, he walks in light rain. 2–4 s: the camera pushes in to his footsteps. 4–5 s: it pulls back to a medium shot as he stops." This gives the feel of several angles without a cut, and can replace an extra scene.

**Kling weak spots: the writer swaps the action and keeps the intent**

| Kling is bad at | Swap to | Example |
| --- | --- | --- |
| Crowds doing complex actions | Crowd still or staring; action on the main subject | "she looks around nervously while the crowd stares in silence" |
| Throws, catches, pouring, liquids | Show before and after, or start the clip after the moment | the cup is already full, steam rising |
| Hands handling small parts | A simple hold or a slow turn of the product | holds the box, turns it to the camera |
| Things changing shape | A cut between two scenes instead | scene 1 closed, scene 2 open |
| Text, logos, screens with words | Added by us in compose | blank screen glow, headline drawn later |
| Fast spins and big jumps | Slow push in, slow orbit | slow 90° orbit around the product |
| Several people interacting | One person, or anchors for each person's place | "P2 stays on the left, seated" |

When the writer swaps something the user typed, it shows up on the storyboard as **"AI changed: \[reason\]"**, so the user can undo it.

## Clip builder: a fixed budget per clip

One function in code (today's `clip_prompt`) builds every Kling text from the slots, most important part first. Each part has a budget, so the text is planned to fit instead of being cut afterwards. A typical clip lands at about 1,000–1,400 characters.

| # | Part | Comes from | Budget (characters) | When over budget |
| --- | --- | --- | --- | --- |
| 1 | Movement: action, camera, timeline | scene card | up to 1,000 (can borrow room that other parts don't use, up to 1,400) | block and offer "Shorten it for me" (as today) |
| 2 | Who and the product | cast sheet, only entries in this shot | up to 400 | keep the product whole, trim the people's details. v2: with no photo, the written product description sits here (A6) |
| 3 | Start and End | continuity | 2 × 180 | cut each to 120 |
| 4 | Place, light, look | cast sheet (or the scene's change) | up to 250 | use the short version |
| 5 | Fixed rules | code | 300 (v2: measured worst case) | never cut |
| – | Avoid and Never | scene card and sheet | 0 here: Kling's separate negative prompt field, with its own 2,500 limit (base list about 110 + the scene's Avoid) | – |

The budgets add up to about 2,310. Borrowing only moves unused room between parts, so the total stays under that, and the 2,500 limit is never reached by accident.

Example of the built text (5 s scene, 2 of 4):

```markdown
0–2 s: handheld medium shot, P1 walks toward the camera through light rain, hood up. 2–4 s: slow push in as he pulls the hood down and smiles at the camera. 4–5 s: he stops; the chest logo faces the camera.
In shot: P1, man, late 20s, short dark hair, black hoodie with white chest logo, grey joggers.
Starts: medium shot, P1 mid-step, camera moving back slowly.
Ends: P1 still, facing the camera, chest logo centred.
Place: wet city street at night, neon signs, soft rain. Realistic, 35 mm, cool blue grade, phone-camera feel.
One continuous take, no cuts; product exactly as in the photo. Realistic phone footage, natural light. Continues from the previous scene's last frame, same move; no restart. End mid-movement.
```

Negative prompt for the same clip: `text, letters, logos added, blur, warping, other people, crowd`.

**v2: fixed rules, rewritten and measured (A2, A6).** Today's rules reach 458 characters in the worst case. The new text below reaches **exactly 300**, so the 300 budget and the 2,310 total stay as they are. Counts include the joining space, and code picks every line; the writer never does.

| Line | Added when | Characters |
| --- | --- | --- |
| "One continuous take, no cuts; product exactly as in the photo." | always, with a product photo | 63 |
| "One continuous take, no cuts; product as described above." | always, no photo (A6; the description is in the "Who and the product" part above it) | 58 |
| Realistic: "Realistic phone footage, natural light." | always, one style line | 40 |
| Cinematic: "Cinematic, smooth stabilised moves, film grade." | ″ | 48 |
| 3D: "3D animation, same CG look in every frame." | ″ | 43 |
| 2D: "2D anime style, same line art and flat shading." | ″ | 48 |
| "Ends exactly on the given end image; move steadily toward it." | the next scene has its own picture, connected video | 62 |
| "Played {X}x faster: keep moves slow." | with the end-image line, scene shorter than the clip | 38 |
| "Only the first {N} seconds are used: fit every beat in them." | no end image, scene of 2–4 s or 6–9 s | 59 |
| "Spread the beats evenly over 10 seconds." | no end image, scene of exactly 10 s | 41 |
| "Continues from the previous scene's last frame, same move; no restart." | connected video only, every scene but the first | 71 |
| "End mid-movement." | connected video only, every scene but the last | 18 |

- **Worst case:** a middle scene in a connected video, 9 s, ending on the next picture, with a product photo and the cinematic or 2D style: 63 + 48 + 62 + 38 + 71 + 18 = **300**.
- **Separate shots worst case:** 170. **Shortest** (one 5 s realistic scene): 103, down from 119.
- **Quirks fixed:** the continue lines are now added only in "One connected video", because in "Separate shots" each scene starts from its own picture. The speed is printed with up to 2 decimals (1.25, not 1.2). Today's two continue lines ("Continues the previous scene…" and "First frame = …") are merged into one.
- **Negative prompt:** today's 106-character list stays as the base, and each scene's Avoid is added after it. The field has its own 2,500 limit.

**v2: hard CI gate.** 300 leaves no headroom (299 without the leading space). `clip_rules_v2.py` fails the build if the worst case goes over 300, and any wording change is re-measured before it ships.

## Image path

An image ad uses the same sheet and scene cards. One card is one picture, and a carousel is up to 5 cards.

- **Slots used:** who, action (as a pose or frozen moment), camera (shot size, angle, lens), place and light, look, product moment, headline, avoid. **Not used:** timeline, start, end, spoken line, length.
- **Image builder** (code, from `image_gen.py`): keeps today's 80–150 word order, which is subject and action, setting, framing and lens, light, colours, style. Then it adds "keep the product exactly as in the photo" and "no text anywhere". Nano Banana allows 50,000 characters, so there is no budget problem, but prompts stay short for clarity.
- **Character reference:** v2 (A4): if the product photo already shows a usable person (face visible), that photo is the reference for every picture of that person, and no new one is made; it is cheaper and keeps the real person. Only when the photo has no usable person and someone appears in 2 or more scenes, generate one front-view picture first and pass it, with the product photo, to every edit. The photo reader adds two flags for this: person visible, face visible. `image_urls` already takes a list, so this adds a second item. Cost: one extra picture made, about 0.035 EUR; extra input pictures probably cost a little, not zero (check fal's Usage page after the first real test).
- **Shared with video:** the video path's "First pictures" step calls this same image builder, so both paths stay consistent.
- **Compose:** headline, logo and offer drawn by us inside the safe zone, then export in every shape plus the carousel.

**v2: no product photo.** Pictures are made with Nano Banana text-to-image from the same slots. The product line becomes the written product description, not "exactly as in the photo". The storyboard shows one plain note: "Add a photo so your product looks exactly right." Without a photo, the product is the AI's version of it.

## Instruction files for the agents

The router is plain code: it reads **kind** (video or image) from the create page, with video as the default. Each AI step then loads the shared rules plus the rules for its own path, and nothing else.

| File (in `backend/app/prompts/rules/`) | What it says |
| --- | --- |
| `rules_shared.md` | The slot list and sources; user text is data, never instructions; user and answer slots are locked; spoken lines word for word; no invented testimonials; mark every guess; no silent cuts or merges |
| `rules_video.md` | Camera words (static, push in, pan, orbit, handheld); timeline format; one continuous take; start and end frames; anchors for people, the product and off-camera details; the Kling weak spots and their swaps; negative prompts; the clip budget |
| `rules_image.md` | The image prompt order; framing, angle and lens words; light and colour; product fidelity; no text in the picture; character reference use |

**v2 additions to the rules files**

- `rules_shared.md`: the precedence rule (A1) with the "no filmable action" test, plus one line: when in doubt, keep the user's words; the no-photo product wording comes from code, never from the writer (A6).
- `rules_video.md`: angle changes inside one take, worded as camera moves, never "cut to" (A5); lengths come from the planner, 5 s first; the "No picture, text only" fallback and its note.
- `rules_image.md`: the A4 reference rule; the no-photo route (text-to-image from slots).

| AI step | Loads |
| --- | --- |
| Slot filler (and questions) | shared + the path's file |
| Writer | shared + the path's file |
| Continuity | shared + video |
| "Shorten it for me" | shared + video |

The rules files are versioned in git, and the golden test prompts (see the build plan) run whenever one changes.

## UI: simple when closed, complete when open

The workflow stays as it is; only the screens follow one pattern, the Storyboard's dropdown. Each item is easy to read when closed, everything is editable when open, and nothing is hidden for good. **Test for every screen:** a first-time user understands it in 5 seconds when it is closed, and an expert can find and edit everything when it is open.

**Scene card, closed** (plain words, no model names or technical terms)

- the picture or a thumbnail
- one or two lines of what happens
- the spoken line
- the length

**Scene card, open** (technical words are fine here)

- the full scene text, with "AI's guess" marked lightly on any guessed part
- the picture prompt and the movement (camera, timeline)
- how it starts and ends
- the cast and world entries it uses, editable in place
- "Show what the AI gets": the exact clip text, its count out of 2,500, and each part against its budget

**Everywhere else**

- **Same steps for every prompt.** A detailed shot list goes straight to the storyboard. A vague idea gets up to 3 questions first, each with answer buttons, "Let the AI decide" and Skip.
- **Problems come with a one-click fix and Undo**, never a list of tasks: "Shorten it for me" (clip too long), "Make the scene longer" (spoken line too long), "Undo the change" (action swapped for Kling), "Split again" (scenes merged).
- **Scene split line** at the top of the storyboard: "We found 3 scenes and 2 notes", with move and merge.
- **Cast and world:** its own dropdown at the top of the storyboard, closed by default. Editing an entry updates every scene that uses it.
- **Create page:** unchanged, plus a Video / Image choice if it is not there yet.

**v2 UI additions**

- **Create page:** the product photo becomes optional. With no photo, a plain note: "Add a photo so your product looks exactly right."
- **Length picker:** stays at 4–52 s (v2.1: quality first). v2.3: if the scenes make a different length, the storyboard shows the real length with "Add scenes" or "Keep" buttons (see Decisions).
- **Cost:** the storyboard shows the projected cost before Continue. If an ad would pass the safety cap, one button appears, "Allow this ad over the cap" (v2.2); nothing is cut and nothing is blocked at payment.
- **Scene picture menu:** adds "No picture, text only", with a small note that the look may change between scenes.
- **"AI changed" mark** on swapped actions (A1), with Undo, in the open scene card.

## Files, build order and tests

This is built in 6 phases. Each phase ships on its own and passes the golden tests before the next one starts. It adds one AI call per ad (the slot filler, under 0.01 EUR).

**Files** (in `backend/app/services/` unless noted)

| File | Change |
| --- | --- |
| `ad_structure.py` (new) | Pydantic models: `Slot(value, source)`, `CastSheet`, `SceneCard`, `AdStructure` |
| `story_beats.py` → `scene_splitter.py` | Add headings, lists, paragraphs and the no-shape fallback |
| `slot_filler.py` (new) | 1 AI call: beats → structure, paragraph split (scene or notes), key-slot gaps, questions with suggestions; code checks the split and asks once more if it fails |
| `router.py` (new, small) | Picks the path and the rules files from kind |
| `storyboard.py` | Writer fills only empty slots; code puts locked slots back |
| `continuity.py` | Writes Start and End into the scene cards |
| `video_gen.py` (`clip_prompt`) | Builds the clip from slots with the budget table; negatives to the negative field |
| `image_prompt.py` (new, from `image_gen.py`) | Builds the Nano Banana prompt from slots; character reference |
| `storyboard_checks.py` | Add: spoken-line length, locked slots unchanged, every key slot filled or marked as a guess |
| `prompts/rules/*.md` (new) | The 3 rules files |
| frontend | Closed and open scene cards, questions screen, light "AI's guess" marks, one-click fixes with Undo, scene split line, cast and world dropdown, budget counter |
| `DECISIONS.md` | D31 onward: the decisions below |

**v2 file changes**

- `scene_plan.py`: becomes the length planner: quality first, cost shown, cap only as a safety limit (A3, v2.1). v2.2: prices come from config, keyed by the exact model ID and output size (for example Nano Banana 2.1 at 1K), plus the USD-to-EUR rate; the test assertions read the same config. Nano Banana Pro or 4K output would make pictures 3–4× dearer.
- `video_gen.py`: new `clip_rules` text and conditions (A2), the no-photo product line (A6), and a per-scene text-to-video fallback (Kling 2.5 Turbo Pro text-to-video on fal).
- `analyze.py`: "person visible" and "face visible" flags (A4); skipped when there is no photo.
- `image_gen.py` / `image_prompt.py`: Nano Banana text-to-image for no-photo ads; the photo's person as the reference (A4).
- `router.py`: routes on kind plus photo or no photo.
- Frontend: optional photo, projected cost on the storyboard, "No picture, text only" option, "AI changed" mark with Undo.
- `tests/fixtures/golden_v2/`: the 6 new test prompts (delivered with this plan). `clip_rules_v2.py` (also delivered) holds the exact rules text and a check that the worst case is 300.

**Build order**

1. Structure models and the 3 rules files. No change in behaviour yet.
2. Scene splitter for every prompt shape.
3. Slot filler with "yours" and "AI's guess" marks, shown on the storyboard.
4. Clip builder with budgets; the writer fills only gaps.
5. Quick questions screen.
6. Image path and the character reference picture.

**Golden tests** (mock writer, run in CI): 8 prompts matching the cases in section 4 of the setup note (no story, short and vague, long without times, "Scene N" without times, timed shot list, more than 5 timed scenes, spoken lines, scene over 2,500), plus the owner's 20 s prompt (its 5 opening paragraphs of notes must not become scenes). For each prompt, check:

- the scene count and lengths;
- the user's words appear unchanged in the clip text;
- every clip is 2,310 characters or less;
- no key slot is empty without an "AI's guess" mark;
- spoken lines are word for word.

Then one real paid run per phase, within the 5 EUR per-ad safety cap (v2.2).

**v2: 6 new golden prompts** (files in `tests/fixtures/golden_v2/`)

| # | Prompt | Must produce | Runs in |
| --- | --- | --- | --- |
| 1 | "guy wearing my hoodie in the rain", photo, Auto | full structure; no key slot empty without "AI's guess"; 1–2 questions with sensible buttons; clips within budget | CI (structure) + live (question quality) |
| 2 | Story with no photo | text-to-image pictures; product from the brief; the A6 product line; clips within budget | CI |
| 3 | "he throws the hoodie to his friend in the crowd" | the swap, the "AI changed" mark, the intent kept | live |
| 4 | 30 s asked, with three 10 s scenes | v2.1: three 10 s scenes kept as asked; cost shown; no trade-off (under the safety cap) | CI |
| 5 | The A5 timestamp-angle wording | one continuous clip, no "cut", within budget | CI |
| 6 | v2.3: 2-scene story, 40 s picked | the real-length line ("Your scenes make a 22 s ad"), both buttons, no stretched scene, no silent mismatch | CI (phase 3) |

**Live tests** use the real writer (a few calls, under 0.01 EUR each) and run by hand before each phase ships, not on every commit.

## Decisions and open points

**Answers to the 6 questions in the setup note**

| # | Question | Decision |
| --- | --- | --- |
| 1 | Always ask, or only on "Help me fill the gaps"? | Ask automatically only when a key slot is empty; always skippable |
| 2 | How many questions? | At most 3 |
| 3 | User's words or the writer's version to Kling? | The user's words as they are, whenever they fit |
| 4 | Cast and world: editable or hidden? | Editable, collapsed under Advanced options |
| 5 | Two clips per scene? | No. 5 scenes of up to 10 s already cover the 52 s maximum (v2.1: not a cost decision) |
| 6 | Same structure for images? | Yes; one card is one picture |

**v2.1: the length planner works quality first (A3, owner's rule).** Cost never removes a rule, an action, a scene or a picture.

1. Each scene gets 5 s or 10 s by what its action needs. A length the user typed is kept.
2. A scene of 6–9 s uses a 10 s clip, trimmed or slowed as today, with no loss of quality.
3. Every scene that needs its own picture gets one. A character reference is made whenever a person is in 2 or more scenes and the photo has no usable person.
4. The storyboard shows the projected cost before Continue: clips (0.35 USD per 5 s, 0.70 USD per 10 s, about 0.32 and 0.64 EUR), pictures (about 0.04 USD, 0.035 EUR each, for Nano Banana 2.1 at 1K output), voice and AI calls. v2.2: rate 1 USD ≈ 0.91 EUR, set in Advanced settings from a real source.
5. The per-ad cap becomes only a **safety limit** against runaway jobs (failed retries, bugs). v2.2: the most a full ad can cost is about 3.50 EUR at real rates: 5 clips of 10 s (about 3.20 EUR), 6 pictures (about 0.22 EUR), plus voice and AI calls. A cap of **5 EUR per ad** never cuts a planned ad and leaves room for 1–2 re-made clips (a failed 10 s clip adds about 0.64 EUR, so a max ad with one retry is about 4.10 EUR). Re-made clips count against the cap, but the cap leaves room for them, so a failure never leaves a scene missing. Owner decided on 21 Nov 2026: 5 EUR per ad for testing, reviewed after the first real results, and again before real customers use the app, where per-ad cost (about 3.50 EUR for a full ad) meets pricing; record this in DECISIONS.md. Today's 4 EUR **per day** is now below the per-ad cap, so it must rise to at least 5 EUR before testing, and more if several runs are planned in one day.
6. v2.2, over the cap: a planned ad can only pass the cap if prices change. If it would, the storyboard shows the cost and one button, "Allow this ad over the cap", for the owner to approve. If a re-made clip would pass the cap during a job, the job pauses with the same button instead of skipping the scene. Nothing is cut and nothing is blocked at payment.

**v2.3: chosen length vs real length.** The planner never stretches a scene (slowing it down or holding a frame) just to reach the picked length, because that lowers quality. When the scenes make a different length from the one picked, the storyboard says so plainly and offers two one-click buttons:

- "Your scenes make a 22 s ad (you picked 40 s)."
- **Add scenes to reach 40 s:** the writer proposes extra scenes that fit the story, marked "AI's guess", up to 5 scenes. Undo is available.
- **Keep 22 s:** the picker updates to match.

It is built in phase 3, with the slot filler and the storyboard marks.

**Checked on 21 Nov 2026**

- **Nano Banana edit takes several pictures:** `image_urls` is a list with no maximum, so the character reference is a second item. Today the code sends 1.
- **Kling negative prompt:** its own field, up to 2,500 characters, separate from the main prompt. `cfg_scale` stays at 0.5; `duration` is "5" or "10".
- **Paragraphs as scenes:** the AI decides inside the call it already makes; code checks and retries once (see the scene splitter).
- **Voice model replacement:** already being handled, outside this plan.
- **UX rule:** simple when closed, complete when open (see UI).

**Still to confirm**

- [ ] Check on fal's Usage page what extra input pictures cost on Nano Banana edit after the first real test (billing is per token, so probably small, not zero).
- [x] Kling 2.5 Turbo Pro text-to-video exists on fal: fal-ai/kling-video/v2.5-turbo/pro/text-to-video (confirmed by review, 21 Nov). Recheck the API docs at build time.
- [x] Freeze the fixed-rules text once the coding agent confirms the measured counts in code (worst case 300). Confirmed in code and CI on 21 Nov 2026: worst case 300, separate shots 170, shortest 103, no photo 295 (`tests/test_clip_rules.py`).
- [ ] After the first real runs, check `cfg_scale` 0.5 with the shorter prompts. If clips drift, test 0.6–0.7 on a paid run before changing it everywhere.
- [x] Confirm the exact Nano Banana model ID and output size the code calls, and pin its price in config (v2.2). The code calls `fal-ai/nano-banana/edit` (not "2.1"), priced at 0.0398 USD per picture in the price table; no size setting is sent, so fal's default output. The owner decided to stay on it and compare other models later using the findings archive (D31).
- [x] Raise the daily cap to at least 5 EUR before the first testing day (v2.2). Done: 10 EUR per day, 5 EUR per ad, 0.91 EUR per USD from the ECB rate of 20 Nov 2026 (D31); Cloud Run changes at the M2 deploy.
- [x] Phase 1 built on 21 Nov 2026 (D31): structure models, the 3 rules files, the shorter fixed rules, golden prompts v2 (product names and photos changed to the owner's test photos, plus 07 for the A4 rule), and the local findings archive.
- [x] Full-frame own pictures on 21 Nov 2026 (D31, from the owner's real 20 s test): an own picture a crop would cut by more than a quarter is extended by Nano Banana, never filled with a blurred copy.
- [x] Phase 2 built on 21 Nov 2026 (D31): `scene_splitter.py` (time ranges, headings, lists; paragraphs wait for the phase 3 slot filler; no shape), notes kept, joins and "cut to" splits said on the storyboard; the 8 prompt shapes of the setup note in `tests/fixtures/prompt_shapes.json`; golden fixtures 04, 05 and 06 pass their scene count and length checks.
- [x] Full-frame extension checked with the real AI on 22 Nov 2026 (one picture, about 0.036 EUR): one seamless 9:16 photo, no blur or bars; the model re-draws the scene slightly.
- [x] Phase 3 built on 22 Nov 2026 (D31): `slot_filler.py` (1 AI call, stage `slots`; sources checked in code; empty key slots guessed and marked; paragraphs marked scene or notes by number, checked in code, asked once more on failure; up to 3 questions stored for phase 5); the writer follows the sheet; "Cast and world" and "What the AI used" with "yours" / "AI's guess" marks on the storyboard (shown in phase 3, editable in place with phase 4); the v2.3 length line with "Add scenes" (marked, Undo) and "Keep"; golden 01, 02, 04 and 06 pass their phase 3 checks. Still open from phase 3: the "We found 3 scenes and 2 notes" line has no move or merge buttons yet (the scenes and notes stay editable on the storyboard).
- [x] The real slot filler checked live on 22 Nov 2026 (golden 01 and 02, 0.0085 EUR): honest marks, paragraphs split well, sensible questions (01 asked 3, the fixture wants 1-2: phase 5); fixed in phase 4: no invented product facts, short camera guesses.
- [x] Phase 4 built on 22 Nov 2026 (D31): `video_gen.build_clip` with the budget table (2,310 at most), the user's scene text word for word, the writer's movement only a timeline, locked slots put back (`restore_locked`), A1 swaps with "AI changed" and Undo, "Never" and "Avoid" in the negative prompt; "Cast and world" and "What the AI used" editable in place (an edit becomes "yours" and reaches the clips); each part against its budget on the page. Golden 01, 02, 04, 05, 06 and 07 pass their phase 4 checks; a user scene over 1,400 characters now asks to be shortened. Still open: golden 03 live with the real writer (owner's go).

**Future items: record in `DECISIONS.md`, don't build now**

- A side-profile character reference, if real runs show the person drifting in profile shots.
- A "same scene, different angle" picture source for carousels.
