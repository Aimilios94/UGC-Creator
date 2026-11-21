# How a prompt becomes an ad (the setup on 21 Nov 2026)

This note is for planning a new way to read any prompt: long or short, with scenes or without, well or badly written.
It describes what the app does **today**, step by step, then where it is weak.
Code: `backend/app/services/` (each step names its file).
Decisions behind it: `DECISIONS.md` D27–D30.

## 1. Tools and hard limits

| Job | Model | Limit that matters | Cost |
|---|---|---|---|
| Read the photo, write the storyboard, continuity check, "Shorten it for me" | OpenAI `gpt-5-mini` (Pydantic AI) | none in practice | under 0.01 EUR per call |
| Picture per scene | fal `nano-banana/edit` (edits the real product photo) | prompt up to 50,000 characters | about 0.035 EUR per picture |
| Clip per scene | fal Kling 2.5 Turbo Pro, image-to-video | **prompt up to 2,500 characters**; clips are only **5 s or 10 s**; optional end picture (`tail_image_url`) | 0.35 USD per 5 s (about 0.30 EUR), 0.70 USD per 10 s |
| Voice | OpenAI `gpt-4o-mini-tts` (shuts down 6 Jan 2027) | about 12 words per scene | about 0.001 EUR per line |
| Compose (cuts, captions, music, end card, shapes) | ffmpeg in our worker | — | free |

Other fixed rules:
- 1 to 5 scenes per ad; each scene is 2 to 10 seconds on screen.
- Cap of 1.75 EUR per ad and 4 EUR per day (local test: 5 EUR).
- The video AI never writes text on screen: all words on screen are added by us in compose.

## 2. The flow, in order

### Step 1. Create page (what the user gives)
- **Required:**
  - a product photo;
  - a product name;
  - "What is it, and why would someone want it?" (10–1,000 characters).
- **Optional:**
  - audience, offer, link;
  - platform and shape (9:16 by default);
  - goal, theme, ad type;
  - visual style (realistic, cinematic, 3D, 2D);
  - voice, music, captions, brand kit.
- **Video length:** Auto, or 4–52 seconds including the 2 s end card.
- **"Your own story or script":** up to **12,000 characters**, with a live counter; nothing is cut.

### Step 2. Read the photo (`analyze.py`, 1 LLM call)
- The vision model describes only what it sees: product type, shape, colours, materials, any printed text word for word, and whether a person is visible.
- This description is used to keep the real product the same in every picture.

### Step 3. Read the story in code, before any AI (`scene_splitter.py`; `story_beats.py` before 21 Nov 2026)
- **Since phase 2 of the strategy plan (D31)** the story's shape is read in this order: time ranges (below), "Scene N" / "Shot N" headings (seconds from the heading or a timeline inside the scene), a list of 2–5 actions, paragraphs (left to the writer until phase 3), no shape. Headings and lists follow the same rules as time ranges below: one scene each, the user's words, the rest as notes, more than 5 joined (and said), "cut to" splits a scene when there is room. The rest of this step describes the time-range rules, unchanged.
- **Timed scenes are detected from time ranges** like `0:00 – 0:04` (also `0.00-0.04`, any dash). At least **two** ranges are needed.
- **Each range starts a scene ("beat"):**
  - its seconds come from the stamps (2–10);
  - its text is the story's own words, up to the next range.
- **A range inside the one before it** (for example "Around 0:02–0:04" inside "0:00 – 0:04") is part of that scene, not a new one.
- **More than 5 ranges:** the two shortest neighbours are merged until there are 5.
- **Notes:** in a timed story, everything that is not inside a range (style, characters, place, light, rules, headings) becomes the **"Style and world notes"**.
- **Before phase 2, a story without time ranges was not split at all**, even with "Scene 1:", "Scene 2:" headings. Now only paragraphs and stories with no shape go to the writer whole (notes empty).

### Step 4. Decide the number of scenes and their lengths, in code (`scene_plan.py`)

| Situation | Scenes | Lengths |
|---|---|---|
| Story with 2+ time ranges | one per range (at most 5) | from the stamps |
| No timed story, length chosen | (length − 2 s end card) ÷ 2.5 s, kept within 1–5 | shared out so each spoken line has time (about 2.5 words per second) |
| No timed story, Auto, with a story | the writer decides (1–5) | the writer's, raised so each spoken line fits |
| No story at all, Auto | 3: hook, demo, call to action | the writer's (usually 5 s), raised so the lines fit |

### Step 5. The writer (`storyboard.py`, 1 LLM call, maybe 2)
- **It gets:**
  - platform, shape, style;
  - the brief;
  - the photo description;
  - the story (as data, never as instructions);
  - for a timed story, "write exactly N scenes, one per beat" with each beat's text;
  - the brand's tone of voice, if any.
- **It writes, for every scene:**
  - **description:** what the viewer sees, in plain words;
  - **image_prompt:** the first picture, 80–150 words in a fixed order: subject and action, setting, framing and lens, light, colours, style. It ends with "keep the product exactly as in the photo".
  - **motion_prompt:** the clip, 100–200 words. A timed shot list ("0–1 s: … 1–3 s: …") of one continuous take, giving camera move and speed, what the subject and product do, and the final frame. It is told to carry the previous scene's movement on and to avoid physics-heavy actions (a throw being caught, pouring).
  - **voiceover:** one short line (about 2.5 words per second), or empty;
  - **on_screen_text:** a short headline.
- **It also writes:** the title, 3 alternative opening lines (hooks, each with a formula) and the button text.
- **With a story, it is told to:**
  - put spoken lines into the voiceover word for word;
  - put every visual detail into the description and both prompts;
  - take timings from the story;
  - add only what the visuals need.
- **If it returns the wrong number of scenes,** it is asked once more (both calls are paid).
- **Code then overrides, for a timed story:**
  - **description** = the beat's own text, whole;
  - **length** = from the stamps;
  - **notes** = the story's notes (step 3).
- **Important:** the clip does **not** use the description. It uses the writer's **motion_prompt** (see step 10). In a timed story, the user's exact words therefore reach the screen and the "What happens" box, but the video AI gets the writer's rewrite of them. Nothing checks that the rewrite kept every detail.
  - The free mock writer copies the beat text into the motion prompt, so the mock browser check showed the user's words in the clip text; the real writer does not.

### Step 6. Testimonial check, in code (`storyboard_checks.py`)
- It looks for invented claims: "I've used this for 3 months", reviews, ratings, awards, results over time, unless the brief or story states them.
- If any are found, the writer is asked once more with those lines as feedback.
- Lines still flagged are shown to the user, and Approve is refused until they are edited.

### Step 7. Continuity check (`continuity.py`, 1 LLM call, D30)
- It reads the whole storyboard and writes only hidden AI instructions:
  - **starts / ends** per scene: camera position, move under way (direction, speed), pose, gaze, light. Scene N's end and scene N+1's start describe the same moment. Where the story jumps, it adds a bridging move (whip pan, push into a dark surface, walk out of frame, match on action).
  - **keep_same:** what stays the same in every scene (lens, height, people and clothes, place, time, light).
  - **notes_short** per scene: the style notes cut down to what this scene shows, within that scene's free room in its 2,500 characters (only when the full notes do not fit).
- Each starts, ends and keep_same line is at most 230 characters.
- If the call fails, the storyboard is kept as written.

### Step 8. Storyboard page (the user checks and edits)
- **Editable:**
  - per scene: what happens, spoken line, headline, length, picture and movement prompts, and starts/ends;
  - the style notes and the hook.
- **Picture source per scene:** Generate, use the product photo, upload a picture, or **Continue from scene N** (the default for later scenes in "One connected video").
- **"One connected video" (default) or "Separate shots".**
- **"Show what the AI gets"** per scene:
  1. the picture prompt;
  2. the movement;
  3. how it joins the scenes around it;
  4. **the exact clip text with its count out of 2,500**.
- **A scene too long on its own** (movement + fixed rules over 2,500) shows by how much, with **"Shorten it for me"** (1 LLM call, keeps the meaning) and Undo. Continue is blocked until it fits.
- "My own story" can be changed here; the storyboard is then written again (steps 5–7).

### Step 9. Pictures (after Approve, `image_gen.py`)
- **For each "Generate" scene:** Nano Banana edits the real product photo with:
  - the image_prompt;
  - "First moment of the shot: [starts]";
  - "Same in every scene: [keep_same]";
  - the **full** style notes;
  - the product-fidelity sentence, "no text anywhere", and the style line.
- **Own pictures** are made the ad's shape: a free centre crop when it keeps at least 75% of the picture, otherwise Nano Banana extends the picture to the full frame (one picture's price; since 21 Nov 2026 never a blurred fill, which Kling animated).
- **"Continue" scenes get no picture yet;** their first frame comes from the previous clip (step 10).
- The user sees the pictures before any clip is paid for, and can still edit the spoken line, headline, movement and length.

### Step 10. Make the video (`pipeline.run_job`, `video_gen.py`)
- **Voice lines first** (cheap), so a voice problem stops the job before any clip is paid for.
- **Then one clip per scene, in order:**
  - A **Continue** scene starts from the previous clip's frame at the moment it is cut, so that cut is clean.
  - If the **next** scene has its own picture, this clip is told to **end on that picture** (Kling end frame).
  - Kling makes only **5 s or 10 s**. A 4 s scene uses the first 4 s of a 5 s clip; a 6–10 s scene pays for 10 s.
  - A clip that ends on the next picture is played whole in the scene's time (5 s in 4 s = 1.25× faster).
- **The clip text** is built in one place (`clip_prompt`), see section 3. A negative prompt is also sent: no text, letters, logos, blur or warping.

### Step 11. Compose (`compose.py`, free)
- **Cuts:**
  - clean on a "Continue" cut;
  - 0.1 s blend onto an end picture;
  - 0.3 s blend between separate shots.
- **A scene is held on its last frame** if its spoken line needs more time.
- **Text and sound:**
  - captions (the voiceover) and headlines are drawn by us inside the platform's safe zone, plus the logo;
  - a 2 s end card with the offer and button;
  - music lowered under the voice, mixed to -14 LUFS.
- **Exports:** 9:16, 1:1, 4:5 and 16:9 (a shape is skipped if its text cannot fit), with "AI-generated" metadata, a cover, one still per scene and a 4:5 carousel.

## 3. The 2,500-character clip text, piece by piece

The order is fixed:

1. **The movement:** the scene's motion_prompt (or its description if empty). Never shortened by the app; if it is too long, the page blocks and offers "Shorten it for me".
2. **Starts** (not scene 1) and **Ends** (not the last scene), up to 230 characters each, in "One connected video".
3. **Same in every scene** (keep_same), only when there are no style notes (the notes already say it).
4. **Style and world:**
   - the full notes if they fit;
   - otherwise "Style and world (short)", the continuity check's version for this scene;
   - otherwise the notes cut at a sentence end.
5. **Fixed rules,** about 290–440 characters:
   - "One continuous take, no cuts; the product stays unchanged";
   - the style line;
   - "ends exactly on the end image" or "only the first N seconds are used";
   - "continues the previous scene… no restart", "End mid-movement", "First frame = the previous scene's last frame".

Example, the owner's 20 s prompt (7,279 characters, 5 timed scenes, 3,371 characters of notes):
- The notes never fit whole in one clip, so every clip gets a per-scene short version.
- On the mock, the clips came to 2,199–2,457 of 2,500.
- With the real writer, the movement is its 100–200-word rewrite (about 600–1,300 characters), so there is more room for the notes.

## 4. How each kind of prompt is handled today

| Prompt | What happens now | Weak point |
|---|---|---|
| No story | 3 scenes (hook, demo, call to action), or the count from the chosen length; the writer invents everything from the brief | Generic; nothing asks the user what they picture |
| Short, vague story ("guy wearing my hoodie in the rain") | Whole text to the writer; it picks 1–5 scenes and fills every gap itself; no notes | Gaps are filled silently; the user does not see what was assumed |
| Long story without times | Same as above; nothing is split or kept as notes | Character and style details survive only if the writer copies them into every prompt |
| "Scene 1: …, Scene 2: …" without times | Since phase 2 (D31): one scene per heading in code, seconds from the heading if given, the text around them as notes; numbered or bulleted lists of actions the same way | Fixed in phase 2; paragraphs still go to the writer until phase 3 |
| Timed shot list (`0:00 – 0:04 …`) | Exact scenes and lengths; beat text kept as the description; notes extracted | The clip still gets the writer's rewrite of the beat (step 5) |
| More than 5 timed scenes | Shortest neighbours merged | Merged scenes carry two beats into one clip |
| Story with spoken lines | Lines go to the voiceover word for word (writer's job, not checked in code) | Not verified; a line too long for its scene is spoken faster or the scene is held |
| Scene text over 2,500 on its own | Blocked with the exact excess; "Shorten it for me" | Fine; the user must act |

## 5. What is missing for "any prompt in, a good ad out"

1. **No questions.** The app never asks the user to fill a gap: who is in it, where, which product moment, how it ends. The writer guesses.
2. **No fixed structure for a scene.** Each scene is free text. There is no checklist (subject, action, camera, start, end, product moment, light) that every scene must fill, so we cannot tell what is missing.
3. **Scene detection depends on time stamps.** Headings, numbered lists or paragraphs are not used.
4. **The user's words are not what Kling reads.** The writer rewrites the movement, and nothing checks that details were kept.
5. **Characters and products are not stored as reusable pieces.** A face or outfit described once is re-written (or lost) in each scene. The per-scene short notes help, but they are written by AI each time.
6. **The 2,500 budget is checked, not planned.** We fit text after writing it, instead of writing each clip to a known budget from the start.
7. **No "what I assumed" view.** Gaps filled by the AI are not marked, so the user cannot confirm or fix them quickly.

## 6. Constraints any new strategy must keep

- **Kling:**
  - at most **2,500 characters** per clip;
  - one start picture, an optional end picture;
  - 5 s or 10 s clips;
  - no on-screen text from the model;
  - physics-heavy actions render badly.
- **Scenes:** 1–5 scenes, 2–10 s each; total cost within 1.75 EUR per ad (a 10 s clip costs double).
- **Rules that stay:**
  - the user's spoken lines are word for word;
  - no invented testimonials;
  - everything the user typed is data, never instructions;
  - nothing paid runs before the user presses Continue / "Make the video";
  - no silent cuts.
- **The average user must not face a long form;** questions must be few and optional, with a sensible default.

## 7. Ideas to discuss (suggestions, not built)

- **A scene card with fixed slots,** filled from any prompt:
  - who and what is in the shot;
  - the action;
  - the camera (shot size, move, speed);
  - the first moment and the last moment;
  - the product moment;
  - place, light and mood.
  
  Slots the prompt did not fill are marked "AI's guess" and shown to the user.
- **A "cast and world" sheet,** written once and reused in every clip (each person's face, hair and clothes; the product; the place; the light and lens; the camera style). Each clip takes only the entries for who and what is in that scene, so it stays within 2,500.
- **Up to 3 quick questions,** only when key slots are empty (for example "Who is in the video?", "Where does it happen?", "How should it end?"). Each has buttons with suggestions and a "Let the AI decide" choice.
- **Scene detection from any shape:** timestamps, "Scene N" headings, numbered lists, paragraphs, or none (then split by the chosen length).
- **A fixed budget per clip,** for example: movement up to about 1,200, start/end 460, cast and world up to about 500, rules about 350. The writer writes to it; no fitting afterwards.
- **Keep the user's exact words in the clip** where they fit (the beat text as the movement), and use the writer only to fill empty slots.

## 8. Questions for the strategy discussion

1. Should a vague prompt **always** get questions, or only when the user presses "Help me fill the gaps"?
2. At most how many questions before the storyboard (0, 3, 5)?
3. Should the user's own scene text go to Kling word for word when it fits, or the writer's cleaner version?
4. Is "cast and world" one sheet the user can edit, or hidden like the start/end lines?
5. Are 5 scenes enough for a 20–30 s ad, or should one scene be allowed two clips?
6. Same structure for image-only ads later, or only for video?
