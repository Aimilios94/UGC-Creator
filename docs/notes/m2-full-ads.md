# M2 — Full ads (design note)

Status: **in progress** on `v2`. Started 19 Nov 2026. The plan is [§17, M2](../plan/ugc-v2-full-plan.md); this note records how it is built and what was decided on the way.

## Done
- **Task 0, CI maintenance ([D23](../../DECISIONS.md)):** `actions/checkout@v7`, `actions/setup-python@v7`, `actions/setup-node@v7`, every job on a pinned `ubuntu-24.04` runner (the image `ubuntu-latest` points to). The first run after the change was green with no annotations (commit `cab5768`).
- **Task 1, ruleset on `main` ([D23](../../DECISIONS.md)):** "main protection" (id `27687215`): force pushes and deletion blocked; the checks `frontend`, `backend` and `docker` required on an up-to-date branch; no reviews; no bypass. `v2` has no rules. Settings and commands: [SETUP](../SETUP.md#github-ci-and-the-ruleset-on-main).
- **Before M2 (not a plan item):** the landing refresh in the v1 look and the Create page with "Soon" previews ([D24](../../DECISIONS.md), PR #4, merge commit `b9ee79e`).
- **Spend limits for 3-scene ads ([D2](../../DECISIONS.md)):** 1.75 EUR per job, 4 EUR per day; live on Cloud Run as env vars.
- **Item 1, campaign brief, brand kit, 3 scenes, testimonial rule ([D25](../../DECISIONS.md), 20 Nov 2026; on `v2`, not deployed):**
  - *Data:* `campaigns` (per session; created from the first ad's brief, later ads join by `campaign_id`), `brand_kits` (one per session: tone, colours, font, logo key), `variants` (A at approval, first hook; B/C in M3). `jobs.campaign_id` and `jobs.brand` (a snapshot of the kit when the brief was sent).
  - *API:* `POST /jobs` takes `campaign_id`, `campaign_name`, `use_brand_kit`; the brief takes `goal`, `theme`, `ad_type`. `GET /campaigns`; `GET`/`PUT /brand-kit`; `POST /brand-kit/logo`. `JobView` adds `campaign_id`, `brand`, `flags`, `variants`. Saving needs the access code; reading does not.
  - *Prompt:* goal, theme and ad type steer the angle; the brand tone wins over the theme; image and motion prompts never ask for lettering, logos or brand colours (compose adds them).
  - *Testimonial rule:* `services/storyboard_checks.py` flags claims the brief does not state; the pipeline rewrites once with the lines as feedback; leftover flags are marked on the Storyboard step and Approve returns 409 until they are edited. Title, call to action and hooks became editable so every flagged field can be fixed.
  - *3 scenes:* `RENDER_SCENES=3` in code and tests (estimate 1.17 USD ≈ 1.02 EUR); Cloud Run pinned to 1 until the M2 deploy.
  - *UI:* Create page goal/theme/ad type/campaign/brand kit live (Soon tags removed); Generate step shows every scene's progress and clip.
  - *Checks:* 100 tests pass (39 new); lint and build clean; the flow checked in a browser on the mock stack.

- **Item 2, compose, voiceover and music ([D26](../../DECISIONS.md), 20 Nov 2026; on `v2`, not deployed):**
  - *Order in the worker:* voice lines → image and video per scene → compose. A voice failure stops the job before any video is paid.
  - *Voice:* `providers/voice.py` (`openai` | `mock`), `gpt-4o-mini-tts`, voices marin/cedar/coral/onyx, tone from the brand kit. **OpenAI shuts the model down on 6 Jan 2027: choose and plug in a replacement before then.** Tokens estimated high; three lines cost well under a cent.
  - *Compose:* silent master with hard cuts (hold or speed up ≤1.15× when a line is longer than its clip); ratios cropped (keeps ≥75%) or fitted on a blurred copy; captions (bold 3-word chunks, clean subtitles, or off) and headlines laid out by us inside the safe zone and burned in by libass; logo top-left; 2 s end card; voice over the ducked music bed, −14 LUFS; AI metadata on every MP4 and JPEG; cover, stills, 4:5 carousel; output checks stored on variant A.
  - *Music:* five CC0 beds, one per theme ([MUSIC.md](../MUSIC.md)). *Fonts:* four OFL fonts.
  - *Checks:* 120 tests pass (20 new: compose on real ffmpeg, AI-metadata guardrail, safe zones, voice spend rules); the full flow checked in a browser on the Docker mock stack (4 ratios in about 26 s).
  - *Deploy notes:* the worker needs the OpenAI key; schema, `RENDER_SCENES=3` and a paid smoke run (SETUP, "M2 deploy").

- **After the owner's first manual test: the user steers the storyboard, images first ([D27](../../DECISIONS.md), 20 Nov 2026; on `v2`):** two steps (Approve → images; "Make the video" → voice, clips, compose), own scene images, own story, hook choice, 5/10 s clips with live prices and an up-front cap check, visual style, detailed image prompts and timed motion shot lists, clickable steps with Back, hover help. 129 tests pass. Local note: the Docker stack prices mock renders like real ones (D14), so a day of local testing can reach the 4 EUR daily limit in the local database; clear it with `docker compose exec -T postgres psql -U postgres -d ugc -c "delete from llm_calls where provider = 'mock'"` (local only). Vite in Docker does not see file changes on a Windows bind mount: `docker compose restart frontend` after frontend edits.

## Next (plan §17, M2)
1. ~~Campaign brief and brand kit; 3 scenes; testimonial rule~~ (done above). Still "Soon" on the Create page: model preset (M4), Hook Lab (M3), email (M3).
2. ~~`compose.py`, voiceover, music~~ (done above).
3. Theme YAMLs for the five themes, with the football pack.
4. Cost tracking for every billing unit, live cost ticker, History page.
5. Sentry (backend and frontend, EU org, with the scrubber), the OpenAPI docs page and a curl example in the README.
6. Token-protected cleanup endpoint on the GitHub Actions cron (retention and stale-job sweep) and "delete my data". **Must also cover item 1's data:** campaigns, brand kits and logo files under `brand/<session hash>/` (not covered by the `jobs/` bucket rule) after 30 days without use, and all of them on "delete my data" (D25, PRIVACY). The sweep token is generated by the agent when the endpoint is built: one value, never printed, stored in Secret Manager (accessor `ugc-api` only) and as a GitHub Actions secret via `gh secret set` from stdin, compared in constant time; recorded in DECISIONS and SETUP.

**Done when** (plan): a 3-scene ad with voiceover, captions, end card and music plays in its master ratio and every derived ratio that passes the safe-zone check; every export carries AI metadata; History shows cost per stage in EUR; a job killed mid-run is recovered or failed by the sweep within one cron interval; expired files are deleted; "delete my data" removes the session's jobs and files at once.

## Inputs for the build
- **Video:** one continuous take per scene clip; a start frame (and an end frame where the model supports it) keeps people and places consistent. Kling's multi-shot mode made the subject jump between places. Avoid beats that depend on object physics. ([feedback round 2](../../feedback-notes.md))
- **Text on screen:** the models write made-up lettering on signs and boards, so captions, offer and end card come only from `compose.py`.
- **Trimming:** `compose.py` can cut a weak span with a short dissolve instead of paying for a re-render.
- **Budget:** about 17 EUR of the 26 EUR project API budget is left for M2–M4 (D24). Every paid smoke run needs the owner's go with an estimate.
