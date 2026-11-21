# Decisions

*Each entry is **Problem → Evidence → Decision → Result**. This is the record of why the product is built the way it is. The plan is [docs/plan/ugc-v2-full-plan.md](docs/plan/ugc-v2-full-plan.md).*

Evidence tags: `[user]` agreed with the project owner before M1 (18 Nov 2026); `[plan]` from the plan; `[eng]` an engineering decision made while building; `[verified]` checked against a provider's docs or API on the date given.

---

## D1 — Milestone PRs merge only when "Done when" passes and the backend is deployed `[user]`

- **Problem:** A milestone can look finished in code while it does not run where users are.
- **Decision:** Work happens on `v2`; one PR per milestone goes `v2` → `main` and is merged only when that milestone's "Done when" list passes on the deployed backend. If the deploy slips to M2, M1 is not merged until then.
- **Result:** `main` only ever holds deployed, verified milestones. M1: PR #1 merged by the owner on 19 Nov 2026 as a merge commit (`64156d1`) after every "Done when" item passed on the deployed stack; `v2` is kept and fast-forwarded to `main` after each merge. One agreed exception: docs-only PRs right after M1 so the public README on `main` is current instead of waiting for M2: #2 (19 Nov 2026, `f657691`, M1 shown as live) and #3 (19 Nov 2026, `360cfbc`, links to both v2 and v1 at the top of the README). Neither contains a code or deploy change.

## D2 — All user-facing money is in EUR `[user]`

- **Problem:** Providers bill in USD; the budget and the user think in EUR.
- **Decision:** Costs are stored in USD as billed and converted at one app-wide fixed rate (`USD_TO_EUR_RATE`, 0.87). Everything the user sets or sees is EUR, with a USD display option under Advanced settings. M1 limits: `JOB_COST_CAP_EUR=1`, `DAILY_SPEND_LIMIT_EUR=3`. `DEMO_POT_EUR` from M4.
- **Result:** The API returns both currencies, so the display switch is instant and no figure is converted twice.
- **M2 raise (owner's decision, 19 Nov 2026): `JOB_COST_CAP_EUR=1.75`, `DAILY_SPEND_LIMIT_EUR=4`.** A full ad renders three scenes, which the M1 cap of 1 EUR cannot hold. Math from the price table (`llm_trace.py`, prices checked 18 Nov 2026), at 0.87 EUR/USD:

  | Item | Math | USD |
  | --- | --- | --- |
  | 3 reference images | 3 × 0.0398 (Nano Banana edit) | 0.1194 |
  | 3 clips | 3 × 5 s × 0.07 (Kling 2.5 Turbo Pro i2v) | 1.0500 |
  | LLM | M1 measured 0.0039 for analyze + storyboard; about 8× that for M2's extra text work | 0.0300 |
  | TTS voiceover | about 15 s, about 250 characters (tts-1 at 15 USD per 1M characters ≈ 0.004; gpt-4o-mini-tts similar) | 0.0100 |
  | Music | licensed library, no per-ad charge | 0 |
  | **Clean ad** | | **1.2094 ≈ 1.05 EUR** |
  | One retry | one video re-render (0.35) + one image retry (0.0398) | 0.3898 |
  | **With one retry** | | **1.5992 ≈ 1.39 EUR** |
  | +15% margin | price drift and estimate error | **1.839 ≈ 1.60 EUR** |

  The cap is that worst case rounded up to 1.75 EUR, so a normal ad never reaches it. The daily limit of 4 EUR allows two worst-case ads (or about three clean ones) on a test day, and keeps a runaway day under about 15% of the 26 EUR project budget. In M2 the retry headroom only covers a crash between submit and saving the prediction ID (the judge and self-fix arrive in M3–M4). To revisit: M3 (Hook Lab about 0.10 EUR, B/C videos about 0.45 EUR each, if counted against the same job's cap) and M4 (the public demo's 2 visitor ads per day). Set in `config.py`, `backend/.env.example` and `deploy/gcp/*.env.yaml`, and applied to the Cloud Run service and job.

## D3 — OpenAI is the default text provider until the M4 eval `[user]` `[verified 2026-11-18]`

- **Decision:** `LLM_PROVIDER=openai` with `gpt-5-mini-2025-08-07` (0.25 / 2.00 USD per 1M input/output tokens), a dated snapshot so a model cannot change under the evals without a config change. Reasoning effort `low`. The M4 comparison decides the default.

## D4 — Old project files are removed in M1 `[user]`

- **Decision:** `.agent/skills/` (two generic copied skills) and `context.md` (folded into `APP_OVERVIEW.md`) are removed; the project document set is created in M1.

## D5 — "Git history no longer holds the key" means this repo's history `[user]`

- **Problem:** The leaked fal key and a personal address were in every commit of a public repo with one fork.
- **Evidence:** The key was still valid on 18 Nov 2026 (it belonged to a second fal account); revoked the same day, confirmed by HTTP 401.
- **Decision:** Revoking the key is the fix. The history purge (`git filter-repo --replace-text`, force-pushed on 18 Nov 2026) cleans this repo only; the fork and GitHub's cache of old commit SHAs are out of reach.
- **Result:** A fresh clone has 0 occurrences of the key or the address in any object.

## D6 — Scheduled cleanup and sweep run every 15 minutes, at an odd minute `[user]`

- **Decision:** The GitHub Actions cron (M2) runs every 15 minutes at an odd minute (fewer collisions with the top-of-the-hour rush), so a crashed job is recovered within about 15–30 minutes. GitHub disables scheduled workflows in public repos after 60 days without repository activity; this is documented in `docs/SETUP.md`.

## D7 — The job's lifecycle lives in one `jobs` row; Approve flips it once `[eng]`

- **Problem:** A double-click or a client retry on Approve must not create two paid jobs.
- **Decision:** A brief creates a `draft` job. Approve is one conditional `UPDATE ... WHERE status = 'draft'`; a repeat finds no draft and changes nothing. The queue is the same table, claimed with `FOR UPDATE SKIP LOCKED` in a short committed `UPDATE` (no transaction held open, which Neon's idle timeout would break). An empty queue exits with code 0.
- **Result:** Pinned by tests: one row and one video submit after a double Approve; an empty-queue execution returns 0.

## D8 — Spend is reserved before each paid stage, under an advisory lock `[eng]`

- **Problem:** "Spend so far plus the estimate must fit under the cap" is racy if two stages check at once, and a crash between submit and record could hide spend.
- **Decision:** Before a paid stage, one transaction takes `pg_advisory_xact_lock`, sums billed costs plus open reservations (job and UTC day), checks the cap and the daily limit, and inserts a `reserved` row with the estimate. After the call the row is `billed` with the cost from the same price table. A submit that fails is `released` (nothing reached the provider). A render the provider finishes with an error keeps its estimate (billing not confirmed, so the cap stays safe). A "try again" never resets spend.
- **Result:** The cap and limit can only be passed by vendor price drift. Pinned by the cap, daily-limit, open-reservation and try-again tests.

## D9 — A model without a price cannot be used `[eng]`

- **Problem:** A price table that returns 0 for an unknown model would let a new model slip past every spend limit.
- **Decision:** `llm_trace.price_for` raises `UnknownPrice`. The table covers every fal billing unit (image, megapixel, second, video, token, character, generic unit) plus modifiers (base fee, audio-on multiplier, per-resolution multiplier). fal's plural unit names are normalised.
- **Result:** One test per unit and modifier; prices carry their source and check date.

## D10 — fal: verified models, request storage off, outputs expire after one hour `[verified 2026-11-18]`

- **Evidence:** fal pricing API: `fal-ai/nano-banana/edit` 0.0398 USD per image; `fal-ai/kling-video/v2.5-turbo/pro/image-to-video` 0.07 USD per second (5 s = 0.35 USD). Both model pages show the "Commercial use" label. Kling has no aspect-ratio input: the clip follows its input image. fal's docs: generated files are kept forever and publicly readable unless a lifecycle is set.
- **Decision:** Every request sends `X-Fal-Store-IO: 0` and `X-Fal-Object-Lifecycle-Preference: {"expiration_duration_seconds": 3600}`; the worker copies each output into our storage at once. The reference image is generated at the master ratio. Inputs are passed as URLs (fal: URLs work with every model, data URIs only with some): a GCS V4 signed URL when hosted; in local dev a fal CDN upload with the same one-hour expiry.
- **Result:** A planned 15 s ad costs about 1.05 USD of video (about 0.91 EUR), below the plan's 1.30 EUR estimate.

## D11 — Jobs are private to the browser session; another session gets 404 `[eng]`

- **Decision:** The browser creates a random session ID (`X-Session-Id`); the server stores only its SHA-256, and every job route filters on it. Another session gets the same 404 as a missing job, so job IDs cannot be probed. Files are served only through signed, expiring URLs: an HMAC over (key, expiry) for local storage, V4 signed URLs for GCS.

## D12 — Generation needs an access code, and production fails closed `[eng]`

- **Decision:** Creating a job, Approve and "try again" require `X-Access-Code` to match `ACCESS_CODES` (constant-time compare). With `APP_ENV=prod` and no codes configured, every generation request is refused. Local dev without codes is open.

## D13 — One short database connection per unit of work, with wake-up retries `[eng]`

- **Problem:** Neon scales to zero; the first connection after idle can fail or be slow.
- **Decision:** `Database.connect` retries with backoff (0.5 s doubling, max 8 s) and a 20 s connect timeout; prepared statements are off for Neon's pooler. No pool: at this scale a connection per unit of work is simpler and never holds a transaction open during a render. The API and the worker build their connection the same way.

## D14 — Mock media is priced as the real model it stands in for `[eng]`

- **Decision:** The mock media provider renders locally (a Pillow image, a 2 KB H.264 clip) but its calls are costed with the real model's price, so tests exercise the cap and daily limit with real numbers. Mock LLM calls cost 0. Docker Compose defaults to mock providers; real providers must be set explicitly.

## D15 — Tests cannot reach a paid API `[eng]`

- **Decision:** `tests/conftest.py` forces mock providers and blanks every key and database URL before the app is imported (environment overrides `backend/.env`), blocks every non-local socket connection, and turns off Pydantic AI's `ALLOW_MODEL_REQUESTS`. In CI, database tests may not be skipped. CI has no secrets.

## D16 — Cloud Run: the API may only start the job; the job has a 45-minute timeout and 1 retry `[verified 2026-11-18]`

- **Evidence:** Cloud Run docs: a job task's default timeout is 10 minutes (max 168 h). `roles/run.jobsExecutor` grants `run.jobs.run` and `run.executions.cancel` but not `run.jobs.runWithOverrides`.
- **Decision:** Worker job: `--task-timeout=45m --max-retries=1`. The API's service account gets `roles/run.jobsExecutor` on the worker job only and starts executions with an empty body (no overrides). The job's service account reads and writes the bucket. Both sign URLs through IAM signBlob (no key files), so each needs `roles/iam.serviceAccountTokenCreator` on itself. Region `europe-west4`.

## D17 — M1 renders scene 1 only `[plan]`

- **Decision:** `RENDER_SCENES=1`: the first pipeline leg is analyze → storyboard → approval → one reference image + one 5 s video. M2 renders all three scenes and composes the ad.

## D18 — Line endings are LF in the repo `[eng]`

- **Problem:** On a Windows checkout with `core.autocrlf`, the Dockerfile's shell commands and YAML can get CRLF line endings.
- **Decision:** `.gitattributes` pins `eol=lf` for text and marks media as binary.

## D19 — Deploy: least privilege per service, cost guards, settings in files `[eng]` `[user]`

- **Decision:** Two service accounts. `ugc-api` reads only the OpenAI key, the database URL and the access codes, and holds `roles/run.jobsExecutor` on the worker job only; it has no fal key, because it never renders (it gets a media stand-in that refuses). `ugc-worker` reads only the fal key and the database URL. Secrets live in Secret Manager in europe-west4. Cost guards (owner's request): the API scales to zero (min 0, max 2 instances); Artifact Registry keeps the last 5 images; the bucket deletes `jobs/*` after 30 days, matching `RETENTION_DAYS`, so future seeded demo ads under another prefix stay. Non-secret settings are in `deploy/gcp/*.env.yaml`.
- **Result (18 Nov 2026):** an execution on the empty Neon queue exited 0; `/health/db` answers; generation without the access code gets 403; CORS allows only the listed site.

## D20 — v1 is preserved as a tag, a release and screenshots `[user]`

- **Problem:** The M1 merge replaces the v1 site, but a later before/after comparison needs v1 as it was.
- **Decision:** Tag `v1-final` on `main` before the merge (`2404369`), a GitHub release "v1 — n8n prototype", full-page screenshots and a list of known issues in `docs/before-after/v1/`, and the v1 build's permanent Vercel URL recorded there. The v1 code is not kept on `main`.

## D21 — The access code is rotated by adding a secret version and disabling the old one `[eng]`

- **Decision:** A new code is generated into `backend/.env` and added as a new version of the `access-codes` secret; the API gets a new revision so it reads `latest`; the old version is disabled. The code is never printed or committed. Done on 18 Nov 2026 and again on 19 Nov 2026 (each time: old code refused, new code accepted, old version disabled). Steps in `docs/SETUP.md`.

## D22 — Account setup follows the milestone that first uses it `[user]`

- **Problem:** Plan §19 lists the Anthropic API key (with spend limits) and the Sentry project under "Before M1", but M1 uses neither: OpenAI is the default text provider (D3), and Sentry arrives in M2 (plan §17).
- **Decision (owner, 19 Nov 2026):** the Sentry project (EU/Frankfurt org) is set up for M2, and the Anthropic key with its spend limit before M4, when the model comparison first needs it. Until then the `anthropic` provider exists in code but is never called outside tests.
- **Result:** the plan's §19 timing is superseded for these two items only; CLAUDE.md and the handoff list them under M2 and M4.

## D23 — M2 starts with CI maintenance and a ruleset on `main` `[user]`

- **Problem:** CI shows deprecation annotations (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`, `ubuntu-latest`), and `main` has no protection: a force push or deletion would succeed. Neither is in plan §17.
- **Decision (owner, 19 Nov 2026):** two tasks are added before the M2 plan items. (1) Update the actions to their current major versions and pin the runner to a specific Ubuntu version. (2) A GitHub ruleset on `main`, created with `gh api`: block force pushes and deletion, require the CI checks `frontend`, `backend` and `docker` with the branch up to date, no required reviews, no bypass list. After it exists, any history rewrite on `main` needs the ruleset lifted first, with the owner's explicit go.
- **Result (19 Nov 2026):** (1) CI uses `actions/checkout@v7`, `actions/setup-python@v7` and `actions/setup-node@v7` on `ubuntu-24.04` (the image `ubuntu-latest` points to; 26.04 exists but would change the OS under the build); the first run was green with no annotations. (2) Ruleset "main protection" (id `27687215`) is active on `main` with exactly these settings; `v2` has no rules. Settings and commands are in `docs/SETUP.md`.

## D24 — The landing page is refreshed before M2, in the v1 look `[user]`

- **Problem:** Until the M4 showcase has real sample ads, the landing page showed three labelled illustrations and a plain layout, and did not look finished. Plan §17 has no landing work before M4.
- **Evidence:** the v1 landing page (`docs/before-after/v1/`) had a stronger look (centred headline, tilted photo cards on a dark purple gradient) but also invented numbers (10x, 95%, 50k+, CTRs, views).
- **Decision (owner, 19 Nov 2026):** a small pass before M2, in its own PR, to make the landing page presentable until M4. It keeps the v1 look with v2 content: our own example scenes (football grip socks, a hiker with a backpack, a game key art with "Coming soon" set in code) and an 11-second football clip in a phone frame; the four real steps instead of v1's numbers; no form on the landing page; a footer with GitHub, docs and v1 links; share tags with a 1200×630 image. The page says the scenes are examples. The assets were made once, outside the app, with Nano Banana Pro (images) and Kling v3 Pro (video) on fal, for 7.33 USD ≈ 6.38 EUR within the owner's 6.4 EUR limit; the clip was trimmed with ffmpeg at no cost.
- **Second pass (owner, 19 Nov 2026):** a "See what's possible" section (three cards, each a two-slide carousel: the product photo, then the ad scene made from it with the photo as reference, which is how the app works) for a basketball, a translucent keyboard and a hoodie with an original dark-fantasy anime print; the hiker replaces the tea scene. The Create page takes the v1 "Start creating" layout and shows the planned brief options (goal, theme, ad type, model preset; Hook Lab and the brand kit, voiceover, music, captions, email) as clickable previews marked "Soon" that are not sent to the API; the access code moves to a slim bar at the top of the form and only the generate button is locked. The first hero card becomes a two-picture carousel (a volleyball spike, then the football trophy). Same models; 14 images for 2.10 USD ≈ 1.83 EUR within the owner's 3 EUR limit. All example assets together: 9.43 USD ≈ 8.20 EUR. They count against the project's API budget of about 26 EUR (plan §16): with the M1 smoke test and the owner's manual run (about 0.78 USD ≈ 0.68 EUR on fal, plus cents of LLM), about 8.9 EUR is spent and about 17 EUR is left for M2–M4, so M2's paid smoke runs and M4's model matrix (hard cap 9 EUR) must be planned against that.
- **Result:** the M4 showcase still replaces these examples with ads made by the app, with their real cost and scores (plan §17).
- **Later spend:** see D28 (voice previews, about 0.006 EUR) and D29 (the owner's local real tests, about 2.16 EUR): about 11.07 EUR used, about 14.9 EUR left (21 Nov 2026).

## D25 — Campaign brief, brand kit and the testimonial rule (M2 item 1) `[user]` `[eng]`

- **Problem:** Plan §17 M2 item 1 needs campaigns, a brand kit and 3-scene ads, and the storyboard rule against invented testimonials. There is no sign-in, so "set once and reused" needs an owner; and a rule kept only in the prompt cannot be tested.
- **Decision (owner, 20 Nov 2026):**
  - **Brand kit per browser session**, like jobs: one `brand_kits` row per session hash (tone, three colours, caption font, logo). Each ad stores a snapshot of the kit in `jobs.brand` when the brief is sent, so a later edit never changes an ad already planned. The tone goes into the storyboard prompt and wins over the theme's tone; colours, font and logo are applied by `compose.py`, never asked of the image or video model.
  - **Testimonial rule in code** (`services/storyboard_checks.py`): first-person claims of use, experience or results, review and rating language, awards, and time-based results are flagged unless the brief states them (a brief sentence the line closely follows, with no new figure). A flagged storyboard is **rewritten once** with the lines as feedback (one extra LLM call, about 0.003 EUR); lines still flagged are **shown on the Storyboard step for editing**, and Approve is refused (409) while any remain. If the rewrite call itself fails, the first storyboard is kept with its flags. Brand voice ("we use organic cotton") is not flagged; only "I" counts as a testimonial subject.
  - **Theme field now**, as a validated value (`sport`, `beauty`, `tech`, `food`, `fashion` or none); the theme YAMLs and the theme/brand-kit override test come with M2 item 3.
  - **`RENDER_SCENES=3` in code and tests only** (later 1–5 scenes, `RENDER_SCENES=5` as the most; D28). `deploy/gcp/*.env.yaml` pin `RENDER_SCENES: "1"` so any deploy before the M2 deploy keeps the M1 leg; the M2 deploy sets 3 together with the paid smoke run, each with the owner's go.
- **Engineering details `[eng]`:** campaigns are created from the first ad's brief (named by the user or after the product) and later ads join with `campaign_id`; another session gets 404, as for jobs. Saving a brand kit or a logo needs the access code on the public deployment (no free file hosting); reading does not. Logos go through the same upload guard as product photos (PNG transparency kept, metadata dropped) and live under `brand/<session hash>/`, which the `jobs/` bucket rule does not cover: **the M2 cleanup endpoint must delete brand kits, campaigns and logo files after 30 days without use, and "delete my data" must remove them** (recorded in PRIVACY). A replaced logo file is kept until then, because planned ads point to it. The ad type "Testimonial" is labelled "your quotes only" and the prompt limits it to claims the brief states. Variant A (first hook) is created at approval and marked done or failed with the job; B and C are M3.
- **Result:** 39 new tests (100 in total), including the plan §15 guardrail "a storyboard contains no first-person use or results claims unless the brief supplies them" (approval refused until the flagged line is edited). Checked in the browser on the mock stack: brand kit saved with a logo, a planted testimonial flagged and blocked, three scene clips rendered.

## D26 — Compose, voiceover and music (M2 item 2) `[user]` `[eng]` `[verified 2026-11-20]`

- **Problem:** Plan §8 steps 8–9 and §17 M2 item 2: turn three scene clips into a finished ad with voiceover, burned-in captions, logo, end card, licensed music, every ratio that fits its safe zone, cover, stills, carousel and AI metadata on every export.
- **Evidence:**
  - OpenAI's docs (developers.openai.com, read 20 Nov 2026): `gpt-4o-mini-tts` 0.60 USD per 1M text tokens and 12.00 USD per 1M audio tokens; **`tts-1`, `tts-1-hd` and `gpt-4o-mini-tts` are deprecated and shut down on 6 January 2027**; the suggested successor (`gpt-realtime-2.1-mini`) does not work with the speech endpoint. The speech endpoint returns audio only (no token counts). OpenAI's usage policies require telling end users the voice is AI-generated.
  - FreePD (the planned music source) has closed. Free Music Archive track pages for the chosen tracks state CC0 1.0; the CC0 legal code waives rights "for any purpose whatsoever, including without limitation commercial, advertising or promotional purposes" ([docs/MUSIC.md](docs/MUSIC.md)).
- **Decisions (owner, 20 Nov 2026):**
  - **Voice:** `gpt-4o-mini-tts` behind a swappable `VoiceProvider` (`openai` | `mock`); a replacement is chosen and plugged in **before 6 Jan 2027**. Four built-in voices are offered (marin by default, cedar, coral, onyx); the brand kit's tone goes into the voice instructions.
  - **End card:** an extra 2 seconds after the scenes (an ad is about 17 s with 5 s clips).
  - **Watermark:** the brand logo only, and only when the brand kit has one; no app branding.
  - **Music:** five CC0 beds (one per theme), picked by the owner from three checked candidates each: ITS A TRAP (sport), Ocean Memory (beauty), Track 1 from "War (Game Commission)" (tech), Toy Box (food), all by HoliznaCC0, and Everything is groovy by Komiku (fashion).
- **Engineering `[eng]`:**
  - Order in the worker: the voiceover lines first (a fraction of a cent, and a voice problem stops the job before any video is paid), then image and video per scene, then compose (free, ffmpeg in the worker). Each voice line is a paid stage with the usual reservation, cache and resume rules; a failed request is released (not billed).
  - Voice cost: tokens are estimated on the high side (1 per 3 characters of text and instructions; 25 audio tokens per second, OpenAI's realtime docs bill about 1 per 50 ms) and billed from the real duration; three lines cost well under a cent. The job estimate includes it.
  - Compose: one silent master (hard cuts; a scene is held on its last frame, or its voice sped up by at most 1.15×, when the line needs longer than the clip); derived ratios are cropped when the crop keeps at least 75% of the frame, otherwise fitted on a blurred copy; captions (the voiceover, 3-word chunks or clean subtitles, or off) and headlines (each scene's on-screen text) are laid out by us inside the platform safe zone and burned in by libass; a ratio whose text cannot fit is not exported, and a master that cannot fit fails the job. Audio: voice over the bed, ducked by a sidechain compressor, normalised to −14 LUFS; the clips' own audio is dropped.
  - Safe zones (`platform_specs.py`) are an approximation of each app's overlays; the M3 checklist verifies them per platform.
  - AI marking: every MP4 has `comment`/`description` with the AI note and `ai_generated=true` plus the IPTC `digitalSourceType` `trainedAlgorithmicMedia`; every JPEG has the note in EXIF ImageDescription and the same IPTC value in XMP. Output checks (`output_checks.py`) read them back with every export: plays, duration, resolution, audio track, AI marking, captions in the safe zone, sound-off readiness.
  - Fonts: Inter, Montserrat, Bebas Neue, Playfair Display, bundled with their SIL OFL licences (`app/fonts/`). PyYAML added; the image installs Debian's ffmpeg (with libass); CI installs ffmpeg for the compose tests.
  - Deploy (with the M2 deploy, owner's go): the worker job needs read access to `openai-api-key` (D19 gave it only the fal key and the database URL).
- **Result:** 20 new tests (120 in total), including the plan §15 guardrail "every exported file carries AI-generated metadata" and compose on fixture clips with real ffmpeg. Checked in the browser on the Docker mock stack: a full ad in all four ratios with captions, logo, end card, music and voice, plus cover, stills and carousel.

## D27 — The user steers the story, the images and the clips; images first, then video `[user]` `[eng]`

- **Problem:** On the first manual test (20 Nov 2026) the owner could not use their own story, choose a hook, use images they already have, choose clip lengths or go back a step; "What we see" looked editable but the image model reads the hidden image prompt; and the prompts were one or two lines, too thin for a good clip.
- **Decision (owner, 20 Nov 2026):**
  - **Two steps:** Approve makes the reference images only (phase `images`); the user checks them, may still edit each scene's voiceover, on-screen text, motion prompt and clip length, and then presses "Make the video" (phase `video`), or keeps the images. Bad images never cost video money (this extends plan §7–8, where approval rendered everything at once; the judge in M3 fits in step 1).
  - **Own images:** per scene, "Generate", "My product photo" or "Upload my own" (free). Own images are fitted to the ad's ratio (crop, or a blurred fill) before the video model sees them.
  - **Own story:** on the Create page or the Storyboard step; the AI turns it into the 3 scenes, keeps the spoken lines word for word and writes the hooks from it (one cheap LLM call). Claims in the user's own story count as supplied for the testimonial rule.
  - **Hook choice:** tick "Keep scene 1 as written", one of the three hook ideas, or "My own hook"; the ticked line becomes scene 1's voiceover and variant A records the hook.
  - **Clip length 5 or 10 s per scene**, prices shown live; a storyboard over the 1.75 EUR cap is refused before anything renders (the worker's own cap check stays).
  - **Visual style:** realistic (default), cinematic, 3D, 2D; it is added to every image and video prompt.
  - **Detailed prompts:** image prompts 80–150 words (subject, setting, composition, camera and lens, light, palette, style); motion prompts a timed shot list for one continuous take (camera move, subject motion, light, final frame), no physics-dependent beats, no lettering (Kling negative prompt). Limits checked on fal (20 Nov 2026): Kling prompt 2,500 characters, durations 5 or 10 s, end-frame image supported (not used yet).
  - **Navigation and help:** the four step pills (Brief, Storyboard, Images, Video) are links once reached, each step has a Back button ("Back to the brief" refills the form; the photo is picked again), and every field and option has a hover explanation.
- **Engineering `[eng]`:** `jobs.phase` (`images` | `video`); `POST /jobs/{id}/story`, `POST /jobs/{id}/scenes/{idx}/image`, `POST /jobs/{id}/video` (idempotent; video fields only, image fields locked). Storage keys of uploads are set only by the server and hidden from the browser; a storyboard sent by the browser cannot point a scene at another file. The AI writes a `StoryboardDraft`; the user-only fields (clip length, image source, hook) start at their defaults. `/config` publishes the unit prices for the live estimate.
- **Result:** 129 tests pass (9 new). Checked in the browser on the Docker mock stack: own story → ticked hook → uploaded scene image → one 10 s scene → images → edited voiceover → video in four formats → back to a refilled brief.
- **Second pass (owner, 20 Nov 2026):** your story leads everything: a script's spoken lines go word for word into the voiceover, a shot list's details and timings go into the image and motion prompts and set each scene's length, and the hooks open that story. With a story, the Scenes and Opening hook sections start folded (one-line summary; open only if you want). **Scene length is 2–10 s** (the video model still renders 5 or 10 s, billed as such, and compose cuts the clip; a typed ad length is split over the scenes, up to 30 s). Approve became **Continue** with a "What to make" choice: images first (default), or images and video in one go (default when every scene uses your own image). 132 tests pass.

## D28 — The story's own structure (1–5 scenes) and the ad's sound `[user]` `[eng]`

- **Problem:** Ads always had 3 scenes, so a story written as 4 shots of 2 s was squeezed into 3; the voice and music could only be set on the Create page, with no way to hear them; long story and prompt text sat in small scrolling boxes; and "What to make" was unclear when the user already had their pictures.
- **Decision (owner, 20 Nov 2026):**
  - **1 to 5 scenes, following the story** (3 without a story); scenes can be added or removed before approval; the first is the hook, the last the call to action, any between are demo. Up to 5 fits the 1.75 EUR cap with 5 s clips. Once the pictures exist, the number of scenes is fixed. `RENDER_SCENES` now means the most scenes rendered (5 in code; Cloud Run still pinned to 1 until the M2 deploy, D25).
  - **Sound card** on the Storyboard and Images steps: voice (four AI voices or **"No voiceover"**), music (the theme's track, **any of the five CC0 tracks**, or none) and captions, each with a ▶ preview; changeable until the video is made (`PUT /jobs/{id}/sound`). No upload of the user's own recording (owner's choice).
  - **Voice previews:** one short line per voice made once with the real `gpt-4o-mini-tts` (owner's go; 4 lines, about 0.0068 USD ≈ 0.006 EUR estimated; `scripts/make_voice_samples.py`, files in `backend/app/voices/`). This also confirmed that the OpenAI project may use the model.
  - **"Next" in plain words:** if every scene has the user's own picture there is one action, "make the video", straight to the Video step; otherwise "Make the video now" (missing pictures first, no stop) or "Check the new pictures first", each with a one-line explanation.
  - **Readable text:** story, scene descriptions and prompts grow to show all their text.
- **Engineering `[eng]`:** roles are set by position on every storyboard; the writer is told to follow the story's beats (1–5) and timings; `GET /voices`, `GET /music` and their previews are public files (CC0 music, our own samples). Without a voice the voice stages and their cost are skipped.
- **Result:** 138 tests pass (6 new). Checked in the browser: a 4-beat story became 4 scenes of 2 s, a scene was added and removed, the voice list played a sample, "No voiceover" and the tech track were picked, and "Make the video now" produced a 10 s ad (4 × 2 s + end card).

## D29 — Video length, the recommended number of scenes, one continuous shot, style notes; the first real test `[user]` `[eng]`

- **Problem:** The owner's manual tests on 20–21 Nov 2026 (local stack, real AI) showed: (1) at every scene change the clip jumped back, because each scene started from its own separate picture; (2) the real writer merged two timed beats of a 4-beat story into one scene; (3) without timestamps nothing tied the number of scenes to the wanted length; (4) a long prompt with style, setting and lighting text before the timed parts had that text glued onto scene 1.
- **Decision (owner, 20–21 Nov 2026):**
  - **Video length** on the Create page (Auto, 10, 15, 20, 30 s or any 4–52 s). The app turns it into scenes of **about 2.5 s** (owner's choice: more, shorter scenes give more detail; 10 s → 3 scenes, 15 s → 5); each spoken line gets the time it needs (about 2.5 words per second) and the rest is shared out. **Timestamps in the story always win.** Auto lets the writer follow the story.
  - **Your structure is kept; a recommendation is offered:** when fewer scenes would suit the length, the Storyboard shows "Recommended: N scenes instead of M" with **Apply** (joins neighbouring scenes into one continuous shot; texts, movements and lines are joined, nothing cut; the second part's times carry on) or **Keep my scenes**, and **Undo**.
  - **How the scenes connect:** **One continuous shot** (scene 2 onward starts from the exact frame where the previous scene is cut; only scene 1 needs a starting picture; the default when the story has timestamps or asks for one take) or **Separate shots** (each scene from its own picture). Either way every cut gets a **0.3 s soft blend**, and every clip instruction carries a fixed continuity rule (continue the previous camera move, no restart; end mid-movement).
  - **Style and world notes (optional):** text in the story that is not a timed part (style, setting, light, continuity rules, headings) is split into its own box on the Storyboard and added to every picture and clip instruction. Empty when the story has none.
- **Engineering `[eng]`:**
  - Number of scenes and their text and lengths are set in code (`story_beats.py`, `scene_plan.py`); a draft with another number of scenes is sent back to the writer once (both calls counted).
  - Every scene has a stable `uid`, so joining, adding or removing scenes keeps each uploaded picture with its own scene (the browser never sends storage keys).
  - Chained frames are taken at the scene's cut (`image` stage, provider `chain`, free, resumable); estimates count only the pictures that are really made.
  - Scene text up to 2,500 characters and voiceover up to 400, so joined scenes always save; API refusals are shown as a readable sentence.
  - Local stack: mock media shows the user's own pictures (a picture is the product photo fitted to the frame, a clip is its picture with a slow push-in; `MOCK_PREVIEW`, off in tests); the Video page shows "About this ad" (tiles, a dotted story list, the model and cost per step) and the player takes each shape's real size.
- **First real tests (owner's go, limit 5 EUR, local stack with the real providers, `DAILY_SPEND_LIMIT_EUR=5` for the test):** one real 3-scene video (5 s clips) and a few storyboards (0.94 EUR), then the owner's extra 2-scene test with the product photo in both scenes (two 10 s clips and the voice, 1.22 EUR): **about 2.16 EUR** in total (2.49 USD: video 2.45 USD, text and voice 0.04 USD), about 2.84 EUR of the 5 EUR test limit left; plus the four voice previews (about 0.006 EUR, D28). Finding: the look was good, the scene changes were visible (fixed by the continuous shot above; scenes with their own pictures still cut hard, see D30).
- **Result:** 146 tests pass. Checked in the browser on the mock stack: a styled 3-beat prompt was split into notes plus 3 scenes, "continuous" was preselected, scenes 2–3 continued from scene 1's cut, and the frames around each cut carry on without a jump.

## D30 — Every scene flows into the next, whatever pictures the user gives `[user]` `[eng]` `[verified 2026-11-21]`

- **Problem:** With D29 a scene only continued from the previous cut when it was set to "Generate"; a scene with the user's own picture (or the product photo) started from that picture, so the cut before it jumped (the owner's 2-scene real test on 21 Nov 2026, both scenes on the product photo). The writer also plans each scene on its own, so how one scene ends and the next begins did not always match.
- **Evidence:** fal's page for `fal-ai/kling-video/v2.5-turbo/pro/image-to-video` (read 21 Nov 2026): optional input `tail_image_url` ("URL of the image to be used for the end of the video"); price "For 5s video your request will cost $0.35. For every additional second you will be charged $0.07."; the page lists no extra charge for the end image; "Commercial use" badge shown. To confirm on fal's Usage page after the first real run.
- **Decision (owner, 21 Nov 2026):** every scene must flow into the next with no visible jump, with one picture at the start, a picture in every scene, or a mix; different scenes still feel like one connected video.
  - **Own picture on the next scene:** the clip before it ends on that picture (Kling's end frame, `tail_image_url`): clip N starts from scene N's picture and ends on scene N+1's picture, so the cut matches.
  - **"Generate" on the next scene:** it keeps starting from the frame where scene N is cut (D29).
  - **Continuity check after the writer:** one cheap LLM call reads the whole storyboard and writes, for every scene, how it starts and how it ends (camera position, direction and speed, the subject's pose, the light), so scene N's end and scene N+1's start describe the same moment, plus what stays the same in every scene (camera language, people and clothes, place, light) and a bridging movement where the story jumps. It fills only the hidden AI instructions, never the story text, spoken lines or on-screen text, and is shown (and editable) as part 3 of "Show what the AI gets".
  - **Cuts in compose:** a chained cut (the same frame on both sides) is a clean cut; a cut onto a clip's end picture gets a very short blend (0.1 s) for the model's small difference; separate shots keep the 0.3 s blend. Measured on the mock stack with an end picture 12 px off (as a model might land): clean cut, biggest frame step 35 and no double image; 0.1 s, 24 and 3 blended frames; 0.2 s, 12 and 6; 0.3 s, 9 and 9 (ghosting with motion). 0.1 s is the default; compose is free, so the real clips can be re-cut at 0, 0.1 or 0.2 s to compare.
  - **Storyboard page:** the choice is now "One connected video" (default for every storyboard) or "Separate shots", with a plain note that every scene connects to the next, also with the user's own pictures. Separate shots work as before.
- **Engineering `[eng]`:**
  - `Scene.starts`, `Scene.ends` and `Storyboard.keep_same` (`services/continuity.py`, stage `continuity`, schema check updated); in a connected video they go into the clip instruction (and the first picture's), after the movement and before the style notes, within Kling's 2,500 characters. If the check fails the storyboard is kept as written. The mock writer has a deterministic stand-in.
  - The end picture is the next scene's stored (already fitted) picture; it is part of the media cache key. The video stage records `ends_on_next`, and compose then plays the whole 5 s or 10 s clip in the scene's length (for example 1.25× for a 4 s scene) so its last frame meets the cut; the clip instruction asks for slow, smooth movement when it is sped up. A clip without an end picture still uses its first seconds.
  - Compose joins blended neighbours with `xfade` and meets clean cuts with `concat` (`xfade` cannot do a zero-length blend). The mock clip with an end picture moves on to it (local preview); ffmpeg 7.1 in the image needs a fixed frame rate on both inputs of a blend.
  - Cost: the continuity check adds one text call per storyboard (well under a cent); the end picture adds nothing per fal's page; clips cost the same.
- **Long stories (owner, 21 Nov 2026, after pasting a 7,279-character styled prompt that the story box silently cut at 4,000):**
  - **Up to 12,000 characters** for the story and its style notes (page and server), with a live counter; nothing is ever cut silently: over a limit the page says by how much and blocks the next step. The scene text, picture and movement boxes lost their silent caps too (the server keeps 12,000 as the outer limit).
  - **Every clip fits Kling's 2,500 characters** (fal OpenAPI `maxLength`, re-checked 21 Nov 2026; Nano Banana edit takes 50,000, so the picture AI gets the full notes): the scene's own movement word for word, the start and end lines, then the user's notes in full when they fit, otherwise a short version for that scene written by the continuity check (only what is visible or matters in that scene: the people in the shot, the product, place, light, camera rules), sized to the room left. "Same in every scene" is left out when there are notes (they say it). The app's fixed rules were made compact (at most about 430 characters) to leave the room to the user's text.
  - **A scene too long on its own** (its movement plus the fixed rules over 2,500) shows "N characters too long" with **"Shorten it for me"** (one cheap text call, stage `shorten`, nothing saved until the user keeps it) and **Undo**; Continue and "Make the video" are refused (409, readable) until every scene fits.
  - **"Show what the AI gets"** shows the exact text each clip gets with its count (`POST /jobs/{id}/clip-texts`, free, for the board on screen; the same function builds the render, so preview and render match).
  - **Fixed on the way:** a time range inside a scene ("0:00 - 0:04 … Around 0:02-0:04 …") was read as a new part and merged back, making scenes 1 and 2 of the owner's prompt 6 s instead of 4 s (10 s clips, over the cap); a range inside the previous one is now a moment of that scene.
  - Checked in the browser on the mock stack with the owner's full prompt: 7,279 characters kept, 5 scenes of 4 s, notes whole (3,371), every clip 2,199–2,457 of 2,500; a scene pushed to 2,682 characters showed "521 characters too long", Continue blocked, "Shorten it for me" brought it to 2,457, Undo restored it.
- **Result:** 155 tests pass (9 new: the check fills only hidden fields and a failed check keeps the board, start/end notes reach clips in a connected video only, every-scene and mixed pictures end on the next picture, separate shots unchanged, the end frame reaches fal and the cache key, a clip that ends on the next picture meets it at the cut while one without jumps, clean cuts and blends keep the ad length). Checked in the browser on the mock stack: a 3 × 4 s story with scene 2 continuing and scene 3 on the user's own picture; part 3 in "Show what the AI gets"; the notes on the Storyboard and Images steps; the finished ad has a clean cut at 4 s and scene 2's clip (5 s played in 4 s) lands on scene 3's picture at 8 s, with frame steps at both cuts no bigger than inside a scene. With the long-story work: **159 tests pass** (4 more: a long story kept whole with every clip within 2,500 and the preview equal to the render, a story over 12,000 refused, a too-long scene refused until shortened, a moment inside a scene not making a new scene).

## D31 — Any prompt becomes an ad through one fixed structure; quality first; the findings archive `[user]` `[eng]` `[verified 2026-11-21]`

- **Problem:** The app only split a story into scenes from time ranges, never asked the user anything, let the writer rewrite the user's movement before it reached Kling (nothing checked that details were kept), stored no reusable characters, and only checked the 2,500-character clip limit after writing (setup note `docs/notes/how-a-prompt-becomes-an-ad.md`).
- **Decision (owner, 21 Nov 2026):** adopt the prompt-to-ad strategy plan (`docs/plan/prompt-to-ad-strategy-plan.md`, v2 to v2.3), built in 6 phases on `v2` **before the rest of M2** (items 3–6 and the deploy) and shipped in the M2 PR. Every prompt is read into one cast and world sheet plus 1–5 scene cards; every slot is marked as the user's, the photo's, an answer or the AI's guess; code builds each Kling and Nano Banana text from the slots with a planned budget per part; up to 3 skippable questions only when a key slot is empty; the screens stay simple when closed and complete when open.
- **Quality first (owner's rule, v2.1):** cost never removes a rule, an action, a scene or a picture; a change that trades quality for cost needs the owner's yes.
- **Money (owner, 21 Nov 2026):**
  - Per-ad cap **5 EUR**, now only a safety limit against runaway jobs: the fullest ad (5 clips of 10 s, 6 pictures, voice, AI calls) is about 3.50 EUR, and 5 EUR leaves room for 1–2 re-made clips. To review after the first real results and before real customers.
  - Daily cap **10 EUR** (two full ads a day).
  - Exchange rate **0.91 EUR per USD**, from the ECB reference rate of 20 Nov 2026 (1 EUR = 1.0990 USD), in the one setting `USD_TO_EUR_RATE`.
  - Project budget raised from about 26 EUR to **50 EUR**.
  - Set in `config.py`, `backend/.env.example`, `docker-compose.yml` and `deploy/gcp/*.env.yaml`; Cloud Run keeps 1.75 EUR and 4 EUR until the M2 deploy. Supersedes the M2 values in D2 and the "storyboard over 1.75 EUR is refused" line in D27 (the refusal stays, at the new cap).
- **Picture model:** stays `fal-ai/nano-banana/edit` (0.0398 USD per picture, no size setting sent, so fal's default output). Other models are compared later using the archive.
- **No-photo ads (amends the full plan's "one product photo" promise):** allowed, with pictures from the written product description; the picture check (judge, M3–M4) then compares against that description instead of the photo.
- **Findings archive (owner's idea):** every local test ad is kept in `C:\dev\ugc-archive\` (outside the repo, written by the local worker only, never on Cloud Run): what went in, the storyboard, the exact text each picture and clip got, every output, the frames before and after every cut, the models, stages and cost, and a `notes.md` checklist the owner fills in. It shows over time what each model can and cannot do. A final-result judge (per-rule scores, about 0.01–0.03 EUR per ad) comes in a later phase.
- **Phase 1, built (no change in what the ad looks like, except the shorter fixed rules):**
  - `services/ad_structure.py`: `Slot` (value + source), `Person`, `CastSheet`, `CastRefs`, `SceneCard`, `Swap`, `Question`, `AdStructure`; `restore_locked` puts back any locked slot a model changed and logs it; `key_gaps` and `guesses` for the gaps and the "AI's guess" marks; `from_storyboard` reads today's storyboard into the structure.
  - `app/prompts/rules/rules_shared.md`, `rules_video.md`, `rules_image.md` and their loader `services/rules.py` (each AI step loads the shared rules plus its path's); not used by the AI steps until later phases.
  - **Shorter fixed rules** in every clip (plan A2 and A6): worst case **300** characters, down from 458; separate shots 170; shortest 103; the speed is printed with up to 2 decimals (1.25, not 1.2); the two continue lines are merged into one and added only in "One connected video"; a no-photo product line exists for later. The style lines were shortened to match. A CI test fails if the worst case passes 300.
  - Golden test prompts in `backend/tests/fixtures/golden_v2/` (the 6 from the review, product names and photos changed to the owner's test photos: the City Harmony hoodie and the Hoca Cai mug; plus 07 for the person-in-the-photo rule). Every expected result is checked now or listed with the phase that will check it; a key with no phase fails the test. The owner's real photos stay in `local-handoff/photos/`; CI makes simple pictures in code. The owner's own 20 s prompt stays local only.
  - The archive (`services/archive.py`, `ARCHIVE_DIR`, mounted only into the local worker): written after every run of a job, never failing it; the exact text each picture and clip got is now kept with its stage (`sent`), so the archive shows what was really sent; older ads show a rebuilt text, marked as such.
- **Result:** 204 tests pass (45 new; 7 golden fixtures report what later phases will check). The local stack rebuilt on the free mock providers shows the new caps and rate; the owner's three real test ads of 21 Nov were archived (the 20 s test: 1.60 EUR, the 4 cuts measured at 3.8–11.2 mean difference out of 255, no jump).
