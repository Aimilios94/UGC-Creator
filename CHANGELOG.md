# Changelog

All notable changes to UGC Ad Builder. Format based on [Keep a Changelog](https://keepachangelog.com). The *why* behind changes lives in [DECISIONS.md](DECISIONS.md).

## [Unreleased]
### Added
- Campaign brief and brand kit (M2 item 1, [D25](DECISIONS.md)). New tables `campaigns`, `brand_kits`, `variants`; `jobs` gain `campaign_id` and a `brand` snapshot. The brief gains goal, theme and ad type. `GET /campaigns`; `GET` and `PUT /brand-kit`, `POST /brand-kit/logo` (sanitised like product photos; transparency kept). All of it is private to the browser session; saving needs the access code. The first ad of a campaign creates it from the brief; later ads join with `campaign_id`. Variant A (the first hook) is created at approval.
- The storyboard rule against invented testimonials, checked in code (`services/storyboard_checks.py`): first-person claims of use, experience or results, reviews, ratings, awards and time-based results are flagged unless the brief states them. A flagged storyboard is rewritten once with the lines as feedback; lines still flagged are marked on the Storyboard step and Approve is refused until they are edited.
- Create page: goal, theme, ad type, campaign and brand kit (logo, three colours, caption font, tone) are live and their "Soon" tags are gone. Model preset, Hook Lab, voiceover, music, captions and email stay "Soon". Storyboard step: title, call to action and hooks are editable. Generate step: progress and clips for every scene.

- Compose, voiceover and music (M2 item 2, [D26](DECISIONS.md)): `services/compose.py` joins the three scene clips into one ad with the voiceover (OpenAI `gpt-4o-mini-tts`, four voices, tone from the brand kit), burned-in captions and headlines inside each platform's safe zone, the brand logo, a 2-second end card (product, offer, call to action) and the theme's music bed (lowered under the voice, mix at −14 LUFS). It exports the master ratio and every derived ratio (crop or blurred fill) whose text fits, plus a cover, one still per scene and a 4:5 carousel. Every MP4 and JPEG carries "AI-generated" metadata (IPTC `trainedAlgorithmicMedia`), and code-graded output checks run on every export. New: `platform_specs.py`, `output_checks.py`, `providers/voice.py`, `voice.py`, `music.py`; stages `voice` and `compose`; asset kinds `audio`, `ad`, `cover`, `still`, `carousel`.
- Five CC0 music beds (one per theme) cut by `scripts/make_music_beds.py`, with their sources and the CC0 legal code in `docs/MUSIC.md` and `docs/music/`. Four caption fonts with their OFL licences in `backend/app/fonts/`.
- Create page: voiceover, music and captions are live (Soon tags removed). Generate step: the finished ad with a tab per format, download links, cover, stills and carousel, and a note to turn on the platform's AI label.

- You steer the story, images and clips ([D27](DECISIONS.md)): images first, then "Make the video" (with a last chance to edit voiceover, text, motion and clip length); per scene "Generate", "My product photo" or "Upload my own" image; your own story (Create page or Storyboard step), kept word for word; a ticked opening hook (as written, one of three ideas, or your own); 5 or 10 s per scene with live prices and the cap checked before rendering; a visual style (realistic, cinematic, 3D, 2D); clickable step pills and Back buttons; hover help on every field and option.
- Storyboard, second pass ([D27](DECISIONS.md)): your story drives scenes, prompts, lengths and hooks; Scenes and Opening hook fold away when you have a story; scene length 2–10 s and a typed ad length (up to 30 s); a neutral Continue with "What to make": images first, or images and video in one go.
- 1 to 5 scenes following your story, add or remove scenes; a Sound card (voice with ▶ previews or no voiceover, any of the five music tracks or none, captions) on the Storyboard and Images steps; "Next" in plain words; text boxes that show all their text ([D28](DECISIONS.md)). Voice previews made once with the real voice model (about 0.006 EUR).
- Detailed prompts: image prompts describe subject, setting, framing, camera, light, colours and style; motion prompts are a timed shot list for one continuous take; Kling gets a negative prompt against lettering.
- Storyboard clarity (owner's manual tests, 20 Nov 2026): the total video length box counts the end card and explains when a number is too short or too long; per-scene clip notes ("the AI makes a 5 s clip and the first 2 s are used"); prices broken down (starting pictures, clips and voice, total) with the AI model named for each; the platform picks its best shape; the suggested title is the product name; one scene per row with "Show what the AI gets"; "First line of the ad" explained in plain words.
- Video step: the video first with "About this ad" (tiles, a dotted story list, the model and cost of each step, total), grouped progress, the player in each shape's real size, extra images folded away. On the local mock stack the clips now animate your own pictures (`MOCK_PREVIEW`).
- Video length on the Create page (about 2.5 s per scene, timestamps win), the recommended number of scenes with Apply (joins neighbours, nothing cut) and Undo, one continuous shot (each scene starts where the previous ended) or separate shots, a 0.3 s blend at every cut, a continuity rule in every clip instruction, and optional style and world notes split from the story and added to every scene ([D29](DECISIONS.md)).
- Every scene flows into the next, with any mix of pictures ([D30](DECISIONS.md)): when the next scene has your own picture (or the product photo), the clip before it ends on that picture (Kling's end frame, `tail_image_url`) and is played in the scene's time; "Generate" scenes still continue from the previous cut. A continuity check after the writer (one cheap text call, new stage `continuity`) writes how each scene starts and ends and what stays the same, only in the hidden AI instructions, shown and editable as part 3 of "Show what the AI gets". "One connected video" is the default for every storyboard, with a plain note on the Storyboard step and on the Images step; separate shots work as before.
- Long stories ([D30](DECISIONS.md)): the story and style notes take up to 12,000 characters with a live counter, and nothing is cut silently anywhere. Every clip fits Kling's 2,500 characters: the scene's movement word for word, then your notes in full or a short version for that scene. A scene too long on its own shows by how much, with "Shorten it for me" (one cheap AI call) and Undo; Continue waits until it fits. "Show what the AI gets" shows the exact text of each clip with its count (`POST /jobs/{id}/clip-texts`, free); new stage `shorten`.

- Prompt-to-ad strategy, phase 1 ([D31](DECISIONS.md)): the fixed structure for any prompt (`services/ad_structure.py`: cast and world sheet, scene cards, slots marked as the user's, the photo's, an answer or the AI's guess, locked slots put back if a model changes them); the three rules files for the AI steps (`app/prompts/rules/`, loader `services/rules.py`); golden test prompts v2 (`backend/tests/fixtures/golden_v2/`), each expected result checked now or listed with the phase that checks it.
- The findings archive ([D31](DECISIONS.md)): every local test ad is kept in `C:\dev\ugc-archive\` with its inputs, storyboard, the exact text each picture and clip got, all outputs, the frames before and after every cut, models, stages, cost and a notes checklist. Local worker only (`ARCHIVE_DIR`); never on Cloud Run. Picture and clip stages now record the text they sent.

- Scene splitter, strategy phase 2 ([D31](DECISIONS.md)): besides timestamps, "Scene N" or "Shot N" headings (with their seconds) and numbered or bulleted lists of actions now set the scenes, in your words; text around them becomes the style and world notes; more than 5 scenes are joined and "cut to" inside a scene makes two scenes, each said in one line on the storyboard. Tests for the 8 prompt shapes of the setup note.
- Slot filler, strategy phase 3 ([D31](DECISIONS.md)): one cheap AI call before the writer reads every ad into the cast and world sheet and one card per scene, each value marked "yours" or "AI's guess" (checked in code); a story of plain paragraphs is split into scenes and notes by the AI and checked in code, in your words. The storyboard shows "Cast and world" and, per scene, "What the AI used". New stage `slots`.
- The real length on the storyboard (plan v2.3, [D31](DECISIONS.md)): "Your scenes make a 22 s ad (you picked 40 s)." with "Add scenes to reach 40 s" (the AI writes scenes that fit the story, marked "Added by the AI", with Undo; `POST /jobs/{id}/scenes/add`, new stage `add_scenes`) and "Keep 22 s" (`PUT /jobs/{id}/length`). Scenes are never stretched to fill time.

- Clip builder, strategy phase 4 ([D31](DECISIONS.md)): every clip is built from the cast and world and the scene's card, each part within its budget (at most 2,310 characters); your scene text reaches the video AI word for word, and the writer adds only a timeline; "Never" and "Avoid" go to the video AI's separate negative prompt. "Exactly what the video AI gets" shows each part against its budget.
- Edit in place ([D31](DECISIONS.md) phase 4): every entry of "Cast and world" and "What the AI used" can be edited; what you type becomes "yours" and goes into every clip that uses it.
- "AI changed" with Undo (plan A1, [D31](DECISIONS.md)): an action the video AI renders badly (a throw, pouring, a busy crowd...) is swapped for a safe version that keeps the intent, said on the scene with the reason and your words; Undo sends your words back.

### Changed
- Clip texts ([D31](DECISIONS.md) phase 4): a scene's own text over 1,400 characters asks to be shortened (it could take about 2,200 before), so who is in it, the place and the rules always fit; "Shorten it for me" rewrites the scene text when that is what is too long. The slot filler no longer invents product facts and keeps camera guesses short. The findings archive keeps each clip's negative prompt.
- Scene counts ([D31](DECISIONS.md) phase 3): on Auto, a story with no shape (no times, headings, list or paragraphs) makes 3 scenes, as the plan says, instead of 1–5 at the writer's choice; in a partly timed story, the untimed scenes share what the picked length leaves after the timed ones.
- Shorter fixed rules at the end of every clip ([D31](DECISIONS.md)): at most 300 characters (was 458), the speed with up to 2 decimals (1.25, not 1.2), one continue line instead of two and only in "One connected video"; shorter style lines. More room for the user's text and notes.
- Money ([D31](DECISIONS.md)): per-ad cap 5 EUR (a safety limit; quality first), daily cap 10 EUR, rate 0.91 EUR per USD (ECB, 20 Nov 2026). Cloud Run changes at the M2 deploy.

### Fixed
- The real writer could merge timed beats of a story into one scene: the number of scenes, their text and lengths now come from the story's timestamps in code ([D29](DECISIONS.md)).
- Saving a storyboard with joined scenes failed on the old 800-character scene text limit (now 2,500; voiceover 400), and the page only said "Something went wrong"; refusals are now shown as a readable sentence.
- Switching the shape on the Video step looked unchanged (fixed player box and a tall cover picture).
- A scene with its own picture cut hard from the scene before it in a continuous shot ([D30](DECISIONS.md)).
- The story box cut pasted text at 4,000 characters without a word (also the scene, picture and movement boxes at 2,200–2,500, and joining scenes); a long styled prompt lost its timeline ([D30](DECISIONS.md)).
- A time range inside a scene ("Around 0:02-0:04") was read as a new part, so a 4 s scene became 6 s (a 10 s clip).
- The local mock clip with an end picture failed on ffmpeg 7.1 in the image (a blend needs a fixed frame rate on both inputs).
- The length warning made the page jump, so the Scenes section did not open on click.
- An own picture of another shape (for example a square photo in a 9:16 ad) was filled with a blurred copy, and Kling animated the blurred bands into every later scene. It is now extended to the full frame by Nano Banana (one picture's price, shown on the page); pictures close to the ad's shape are still cropped for free ([D31](DECISIONS.md)).

### Changed
- The Docker image installs ffmpeg; CI installs it for the compose tests. PyYAML added.
- Ads have 1 to 5 scenes in code and tests (`RENDER_SCENES=5` is the most rendered, [D28](DECISIONS.md); 3 without a story or length; a 3-scene ad of 5 s clips is estimated at 1.17 USD ≈ 1.02 EUR). Cloud Run stays pinned to 1 scene (`RENDER_SCENES: "1"` in `deploy/gcp/*.env.yaml`) until the M2 deploy, which sets it with the owner's go.
- Cuts in compose ([D30](DECISIONS.md)): a clean cut where both sides are the same frame (chained), a 0.1 s blend where a clip ends on the next picture, the 0.3 s blend only for separate shots; clean cuts use `concat`, blends `xfade`.
- Docker Compose passes `DAILY_SPEND_LIMIT_EUR` through, for a local paid test (the owner's test used 5 EUR).
- CI: `actions/checkout`, `actions/setup-python` and `actions/setup-node` moved to their current major version (v7), and every job runs on a pinned `ubuntu-24.04` runner instead of `ubuntu-latest` ([D23](DECISIONS.md)). The Node 20 deprecation warnings are gone.
- GitHub ruleset "main protection" on `main`: force pushes and deletion blocked; the CI checks `frontend`, `backend` and `docker` must pass on an up-to-date branch; no required reviews, no bypass ([D23](DECISIONS.md), settings in `docs/SETUP.md`).

### Docs
- Privacy notice (in-app and `docs/PRIVACY.md`): the "Soon" fields on the Create page stay in the browser and are not sent. Updated for M2 item 1: campaigns and the brand kit (with the logo) are stored per browser session, and the M2 cleanup deletes them after 30 days without use.
- M2 design note started (`docs/notes/m2-full-ads.md`); feedback round 2 records what the landing assets taught for the video pipeline; D24 records the project spend so far (about 8.9 EUR of the ~26 EUR API budget).
- Feedback round 3 (the owner's manual tests, 20–21 Nov 2026) and the real tests' spend (about 2.16 EUR: the 3-scene video 0.94 EUR and the owner's extra 2-scene test 1.22 EUR, [D29](DECISIONS.md)); project spend about 11.07 EUR, about 14.9 EUR left.

M2 continues: themes, cost tracking and History, Sentry and the docs page, the cleanup cron and "delete my data", then the M2 deploy.

## [Landing refresh and spend limits] — 2026-11-19 (PR #4, merge commit `b9ee79e`, merged 23:39 UTC)
### Changed
- Landing page refreshed in the v1 look with v2 content ([D24](DECISIONS.md)): centred headline with tilted example scenes (a volleyball and grip-socks carousel, a hiker, game art marked "Coming soon") and a looping football clip in a phone frame; the four steps as one strip; "Create an ad" and "See how it works" buttons; footer links to GitHub, docs and v1; Open Graph and Twitter share tags with a 1200×630 image. A "See what's possible" section: three cards (basketball, keyboard, anime-print hoodie), each a two-slide carousel from the product photo to the ad scene. The scenes are marked as examples. Example assets: Nano Banana Pro and Kling v3 Pro on fal, 9.43 USD ≈ 8.20 EUR in total, made once outside the app.
- Create page in the v1 "Start creating" layout: the planned brief options (goal, theme, ad type, model preset, and under advanced options Hook Lab, brand kit, voiceover, music, captions, email) are shown as previews marked "Soon" and not sent to the API; the access code is a slim bar at the top of the form, and only the generate button is locked until it is entered. Unused v1 images removed from `frontend/public/assets/`.
- Spend limits raised for full 3-scene ads: per-job cap 1 → 1.75 EUR, daily limit 3 → 4 EUR (owner's decision, 19 Nov 2026; math in [D2](DECISIONS.md)). Set in `config.py`, `backend/.env.example` and `deploy/gcp/*.env.yaml`, and applied to the Cloud Run API and worker job. The `/config` test now expects the 1.75 EUR cap (it still expected 1.0, so CI on `v2` was red from that commit until this fix).

### Security
- The access code was rotated again (19 Nov 2026); old secret versions disabled.

### Docs
- README: M1 shown as live (docs-only PR #2, `f657691`).
- README: a "Try it" line at the top with links to both v2 (current) and v1 (the original n8n prototype, frozen) (docs-only PR #3, `360cfbc`). APP_OVERVIEW links the v1 site too.

- Consistency pass (19 Nov 2026): PRIVACY.md says bucket files are already deleted after 30 days (database rows from M2); the first access-code rotation has its own section below; merge times in UTC; DECISIONS [D22](DECISIONS.md) (Anthropic key before M4, Sentry in M2) and [D23](DECISIONS.md) (CI maintenance and a ruleset on `main` open M2).

## [v2 M1] — 2026-11-19 (PR #1, merge commit `64156d1`)

Secure base and first pipeline leg. Live at https://ugc-creator-delta.vercel.app (API on Cloud Run, europe-west4). Production checked after the merge: the site reaches the API, CORS allows it, and the access-code gate refuses a wrong code.

### Added
- **Python backend** (`backend/`): FastAPI API and a worker that share one Docker image. A brief and one product photo produce a product analysis and a 3-scene storyboard with three tagged hooks; after approval, scene 1 gets a reference image of the real product (Nano Banana edit on fal) and a 5-second image-to-video clip (Kling 2.5 Turbo Pro on fal).
- **Spend controls:** one price table for every billing unit, a per-job cost cap and a global daily spend limit checked before every paid stage, all in EUR at one fixed rate ([D2](DECISIONS.md), [D8](DECISIONS.md), [D9](DECISIONS.md)).
- **Job runner:** idempotent Approve, `SKIP LOCKED` claim, resume from `stage_runs` (a submitted render is polled, never paid twice), max 2 attempts with the error stored and shown, empty queue exits 0.
- **Privacy and access:** session-scoped jobs, signed expiring file URLs, an access-code gate that fails closed in production, an upload guard that strips EXIF/GPS, fal request storage off and fal outputs expiring after one hour.
- **Database:** `db/schema.sql` (jobs, scenes, stage_runs, assets, media_cache, llm_calls) with pgvector, applied by `backend/scripts/apply_schema.py`; Neon connections retry while the database wakes up.
- **Frontend:** a guided flow (Brief → Storyboard → Generate) with stage status, live cost and a player; an honest landing page; a privacy notice naming each provider; `lib/api.js`.
- **Docker Compose** (postgres with pgvector, api, worker, frontend; mock providers by default) and **CI** (eslint + build, ruff + pytest on a Postgres service container with mock providers and blocked network, Docker build and start).
- 61 backend tests, including the ten M1 guardrails of the plan.
- **Deployed:** Cloud Run API and worker job in europe-west4, private bucket with a 30-day rule on `jobs/`, secrets in Secret Manager with per-service access, Artifact Registry keeping the last 5 images ([D19](DECISIONS.md)).
- **Live smoke test (18 Nov 2026):** one paid run on the v2 preview: storyboard → approval → reference image → 5 s video, finished with the browser closed; recorded cost 0.3425 EUR.
- Project documents: DECISIONS, APP_OVERVIEW, problem statement, roadmap, setup and privacy docs, M1 design note.

### Changed
- The page title is "UGC Ad Builder"; the landing page no longer shows invented statistics or view counts, and its illustrations are labelled as such.

### Removed
- The v1 n8n frontend components, unused CSS and `framer-motion`.
- `frontend/public/assets/user_upload.png` (a browser screenshot, not a product photo; it stays in old history).
- The "portfolio project" wording from the footer, the privacy notice and APP_OVERVIEW.
- `.agent/skills/` (two generic copied skills) and `context.md` (folded into `APP_OVERVIEW.md`).

## v1 preserved (18 Nov 2026)
- Tag `v1-final` on `main` before the M1 merge and the GitHub release "v1 — n8n prototype".
- `docs/before-after/v1/`: full-page screenshots of the v1 production site and its known issues; the build stays online at its permanent Vercel URL.

## Access-code rotation (18 Nov 2026)

### Security
- The access code was rotated for the first time (new value in `backend/.env` and Secret Manager, old secret version disabled, old code refused) ([D21](DECISIONS.md)).

## Author identity (18 Nov 2026)

### Changed
- Every commit's author and committer rewritten from an unlinked `aimilios944` noreply address to `Aimilios94 <181588880+Aimilios94@users.noreply.github.com>` (`git filter-repo --mailmap`), so GitHub links them to the account. File contents, dates and messages (including the `Co-Authored-By` lines) are unchanged. Force-pushed on the owner's go.

## Step 0 — security clean-up (18 Nov 2026)

### Security
- The fal key that was public in the v1 workflow file was revoked (confirmed dead: HTTP 401).
- The v1 workflow moved to `legacy/n8n/`, sanitised: placeholders for the key, the recipient address and credential IDs; instance, workflow and webhook IDs removed.
- The key and the address were purged from this repo's git history with `git filter-repo --replace-text` and force-pushed. A fork and GitHub's cache of old commits are out of reach ([D5](DECISIONS.md)).
- `backend/.env.example` and `frontend/.env.example` list every setting by name.

## v1 — January 2026 (prototype, kept in `legacy/n8n/`)

A React/Vite landing page posting to an n8n workflow (GPT-4o → Flux Schnell → Kling → Gmail) through an ngrok tunnel. An audit in November 2026 found that it never worked end to end: the form's email field was never read, the frontend posted to n8n's test-only webhook path, and the text-to-image step meant the real product never appeared in the ad. The workflow's notes and the landing page named NanoBanana and Veo 3.1 while the nodes used Flux and Kling. v2 is the rebuild.
