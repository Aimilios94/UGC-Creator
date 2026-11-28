# Privacy: data flows

The in-app notice is `frontend/src/pages/Privacy.jsx`. This page is the engineering view of the same flows. Last checked: 22 Nov 2026.

| Data | Where it goes | Region | Kept |
| --- | --- | --- | --- |
| Product photo (EXIF/GPS stripped on upload) | Our storage; OpenAI (analysis); fal (image edit) | GCS europe-west4; OpenAI US; fal US | Ours: the bucket deletes files under `jobs/` after 30 days (lifecycle rule, live since M1). fal: request storage off (`X-Fal-Store-IO: 0`) |
| Brief text (with goal, theme, ad type, your own story and its style notes, video length, your answers to the quick questions) | Database; OpenAI (slot filler, storyboard, added scenes) | Neon Frankfurt; OpenAI US | Database rows: deleted with the ad 30 days after its last change, or at once by "delete my data" (since M2) |
| Campaign brief (name, goal, audience, offer, landing URL) | Database, per browser session | Neon Frankfurt | 30 days without use, or "delete my data" (since M2) |
| Brand kit (tone, colours, font) | Database, one per browser session; the tone goes to OpenAI in the storyboard prompt | Neon Frankfurt; OpenAI US | Until "delete my data" or 30 days without use (since M2) |
| Brand logo (metadata stripped like photos) | Our storage under `brand/<session hash>/` | GCS europe-west4 | Not covered by the `jobs/` bucket rule: deleted by the cleanup (30 days without use) and "delete my data" (since M2) |
| Scene pictures you upload (EXIF/GPS stripped) | Our storage under `jobs/<id>/scene-N/`; fal (the video model animates them; the image model extends one whose shape is far from the ad's, D31) | GCS europe-west4; fal US | 30-day bucket rule; fal: request storage off, outputs expire after 1 h |
| Voiceover lines (from the storyboard) | OpenAI (text to speech) → audio stored with the job | OpenAI US; GCS europe-west4 | Audio under `jobs/` (30-day bucket rule); OpenAI: API data sharing off |
| Composed ads, cover, stills, carousel | Made in the worker (ffmpeg), stored with the job under `jobs/<id>/variant-A/` | GCS europe-west4 | 30-day bucket rule; every file is marked AI-generated in its metadata |
| Generated images and clips | fal → copied to our storage at once | fal US (expire after 1 h); GCS europe-west4 | fal: 1 hour (`X-Fal-Object-Lifecycle-Preference`). Ours: files deleted after 30 days by the bucket rule (since M1); their database rows from M2 |
| Job status, costs | Database | Neon Frankfurt | Cost rows stay for the daily limit (job link set to null on delete) |
| Browser session ID | Browser localStorage; only its SHA-256 on the server | — | Until the user clears the browser |
| IP address | Vercel and Cloud Run request logs | Vercel edge; Google europe-west4 | Provider log retention |
| Error reports (only when an error happens) | Sentry (`ugc-api`, `ugc-web`) | Sentry EU (Frankfurt) | Sentry's retention (90 days on the free plan) |

Not collected: accounts, names, analytics, tracking cookies. The fields still marked "Soon" on the Create page (model preset, Hook Lab, email) stay in the browser and are not sent to the API (D24); goal, theme, ad type, campaign, brand kit (D25), voice, music, captions (D26), your own story, style notes and video length (D27–D29) are sent since M2. The email address for the Post Kit arrives in M3 (stored only to send, then deleted); LangSmith (M4) is added to this table when it ships.

**Error reports (Sentry, since M2):** on only where a Sentry DSN is set. A report holds the error type, the stack trace, the page or API path and IDs such as the job ID. It never holds the brief, the story, photos, request bodies, headers, cookies, query strings, local variables, the user's IP address or location: the SDK's own collection is switched off category by category, a scrubber in our code (`backend/app/services/monitoring.py`, `frontend/src/lib/monitoring.js`) replaces emails, web addresses and the access code and cuts long texts before a report leaves, and both Sentry projects have "Prevent storing of IP addresses" on plus a rule that removes the location. No tracing, session replay or logs are sent.

**Findings archive (D31), local test runs only:** the owner's local Docker worker keeps a copy of each test ad (inputs, prompts, outputs, frames at the cuts, costs) in a folder on the owner's computer, outside the repo, to learn what each model can do. It is switched on only by `ARCHIVE_DIR`, which only the local Compose worker sets; the live site (Cloud Run) never sets it, so visitors' photos and ads are never kept there.

## Rules in code
- Upload guard: JPEG/PNG/WebP only, size cap, full decode, re-encode from pixels (no metadata survives) — `backend/app/services/uploads.py`.
- Jobs are reachable only from the creating session; other sessions get 404 — `backend/app/routers/jobs.py`. Campaigns and the brand kit are scoped the same way — `routers/campaigns.py`, `routers/brand_kit.py`.
- Retention and "delete my data" (D34): a token-protected cleanup (`POST /admin/cleanup`, every 15 minutes from GitHub Actions) deletes each ad with its files 30 days after its last change, and brand kits, logos and campaigns after 30 days without use; `DELETE /my-data` (the Privacy page button) deletes everything of the calling browser session at once, never another session's, and waits while one of its ads is being made. Cost rows stay without the job link, for the daily limit — `backend/app/services/cleanup.py`.
- Files are private; URLs are signed and expire (`SIGNED_URL_TTL_SECONDS`, default 15 minutes).
- fal privacy headers on every request — `backend/app/services/providers/media.py`.
- OpenAI: the project "ugc-ad-builderv2" has data sharing turned off.
