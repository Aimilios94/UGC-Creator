# Privacy: data flows

The in-app notice is `frontend/src/pages/Privacy.jsx`. This page is the engineering view of the same flows. Last checked: 19 Nov 2026.

| Data | Where it goes | Region | Kept |
| --- | --- | --- | --- |
| Product photo (EXIF/GPS stripped on upload) | Our storage; OpenAI (analysis); fal (image edit) | GCS europe-west4; OpenAI US; fal US | Ours: the bucket deletes files under `jobs/` after 30 days (lifecycle rule, live since M1). fal: request storage off (`X-Fal-Store-IO: 0`) |
| Brief text | Database; OpenAI (storyboard) | Neon Frankfurt; OpenAI US | Database rows: until deleted; automatic 30-day deletion and "delete my data" arrive in M2 |
| Generated images and clips | fal → copied to our storage at once | fal US (expire after 1 h); GCS europe-west4 | fal: 1 hour (`X-Fal-Object-Lifecycle-Preference`). Ours: files deleted after 30 days by the bucket rule (since M1); their database rows from M2 |
| Job status, costs | Database | Neon Frankfurt | Cost rows stay for the daily limit (job link set to null on delete) |
| Browser session ID | Browser localStorage; only its SHA-256 on the server | — | Until the user clears the browser |
| IP address | Vercel and Cloud Run request logs | Vercel edge; Google europe-west4 | Provider log retention |

Not collected: accounts, names, analytics, tracking cookies. The fields marked "Soon" on the Create page (email, logo, brand colours and the other previews) stay in the browser and are not sent to the API (D24). The email address for the Post Kit arrives in M3 (stored only to send, then deleted); Sentry (M2, EU region, with a scrubber) and LangSmith (M4) are added to this table when they ship.

## Rules in code
- Upload guard: JPEG/PNG/WebP only, size cap, full decode, re-encode from pixels (no metadata survives) — `backend/app/services/uploads.py`.
- Jobs are reachable only from the creating session; other sessions get 404 — `backend/app/routers/jobs.py`.
- Files are private; URLs are signed and expire (`SIGNED_URL_TTL_SECONDS`, default 15 minutes).
- fal privacy headers on every request — `backend/app/services/providers/media.py`.
- OpenAI: the project "ugc-ad-builderv2" has data sharing turned off.
