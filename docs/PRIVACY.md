# Privacy: data flows

The in-app notice is `frontend/src/pages/Privacy.jsx`. This page is the engineering view of the same flows. Last checked: 21 Nov 2026.

| Data | Where it goes | Region | Kept |
| --- | --- | --- | --- |
| Product photo (EXIF/GPS stripped on upload) | Our storage; OpenAI (analysis); fal (image edit) | GCS europe-west4; OpenAI US; fal US | Ours: the bucket deletes files under `jobs/` after 30 days (lifecycle rule, live since M1). fal: request storage off (`X-Fal-Store-IO: 0`) |
| Brief text (with goal, theme, ad type, your own story and its style notes, video length) | Database; OpenAI (storyboard) | Neon Frankfurt; OpenAI US | Database rows: until deleted; automatic 30-day deletion and "delete my data" arrive in M2 |
| Campaign brief (name, goal, audience, offer, landing URL) | Database, per browser session | Neon Frankfurt | As the brief text (M2 cleanup) |
| Brand kit (tone, colours, font) | Database, one per browser session; the tone goes to OpenAI in the storyboard prompt | Neon Frankfurt; OpenAI US | Until "delete my data" or 30 days without use (M2 cleanup) |
| Brand logo (metadata stripped like photos) | Our storage under `brand/<session hash>/` | GCS europe-west4 | Not covered by the `jobs/` bucket rule: deleted by the M2 cleanup (30 days without use) and "delete my data" |
| Scene pictures you upload (EXIF/GPS stripped) | Our storage under `jobs/<id>/scene-N/`; fal (the video model animates them) | GCS europe-west4; fal US | 30-day bucket rule; fal: request storage off, outputs expire after 1 h |
| Voiceover lines (from the storyboard) | OpenAI (text to speech) → audio stored with the job | OpenAI US; GCS europe-west4 | Audio under `jobs/` (30-day bucket rule); OpenAI: API data sharing off |
| Composed ads, cover, stills, carousel | Made in the worker (ffmpeg), stored with the job under `jobs/<id>/variant-A/` | GCS europe-west4 | 30-day bucket rule; every file is marked AI-generated in its metadata |
| Generated images and clips | fal → copied to our storage at once | fal US (expire after 1 h); GCS europe-west4 | fal: 1 hour (`X-Fal-Object-Lifecycle-Preference`). Ours: files deleted after 30 days by the bucket rule (since M1); their database rows from M2 |
| Job status, costs | Database | Neon Frankfurt | Cost rows stay for the daily limit (job link set to null on delete) |
| Browser session ID | Browser localStorage; only its SHA-256 on the server | — | Until the user clears the browser |
| IP address | Vercel and Cloud Run request logs | Vercel edge; Google europe-west4 | Provider log retention |

Not collected: accounts, names, analytics, tracking cookies. The fields still marked "Soon" on the Create page (model preset, Hook Lab, email) stay in the browser and are not sent to the API (D24); goal, theme, ad type, campaign, brand kit (D25), voice, music, captions (D26), your own story, style notes and video length (D27–D29) are sent since M2. The email address for the Post Kit arrives in M3 (stored only to send, then deleted); Sentry (M2, EU region, with a scrubber) and LangSmith (M4) are added to this table when they ship.

## Rules in code
- Upload guard: JPEG/PNG/WebP only, size cap, full decode, re-encode from pixels (no metadata survives) — `backend/app/services/uploads.py`.
- Jobs are reachable only from the creating session; other sessions get 404 — `backend/app/routers/jobs.py`. Campaigns and the brand kit are scoped the same way — `routers/campaigns.py`, `routers/brand_kit.py`.
- Files are private; URLs are signed and expire (`SIGNED_URL_TTL_SECONDS`, default 15 minutes).
- fal privacy headers on every request — `backend/app/services/providers/media.py`.
- OpenAI: the project "ugc-ad-builderv2" has data sharing turned off.
