# UGC Ad Builder — App Overview

## What it is
A studio that turns one product photo and a short brief into a finished, ready-to-post video ad in the user-generated-content (UGC) style, with everything a marketer needs to publish it, and then measures how the ad performs.

**One line:** product photo + brief in → storyboard you approve → a video ad that keeps your real product in every frame, with the cost of every step shown.

## Who it's for
Small brands and marketers who need short social video ads (TikTok, Instagram Reels, YouTube Shorts, Facebook) without a shoot. There is no sign-in: each browser sees only the ads it created.

## Core ideas
- **The real product stays in the ad.** The uploaded photo is edited into each scene (image editing, not text-to-image), and each scene image is animated (image-to-video).
- **Nothing paid runs before approval.** The AI writes a storyboard (3 scenes, or 1–5 following the user's own story and chosen video length) with three ideas for the first line; the user edits and approves it first.
- **The user steers (M2, on `v2`).** Their own story and structure lead, pictures they already have can be used, and the scenes form one connected video, each flowing into the next whatever pictures are used, or separate shots.
- **Cost is known and capped.** Every paid step is estimated from one price table, checked against a per-ad cap and a daily limit, and shown live in euros.
- **Measured, not asserted** (from M3–M4): an AI judge scores images and clips, self-fix retries are counted, and the evaluation harness gates changes in CI.

## The flow
Brief → Storyboard → Generate → Review → Launch kit → Performance. On `v2` (M2) Generate is two steps, **Pictures** then **Video**, with "make the video now" when the pictures need no check. Milestones add the later steps:

| Milestone | What ships |
| --- | --- |
| M1 ✅ (live since 19 Nov 2026) | Brief, storyboard, approval, scene 1 image + video, cost cap, privacy notice, CI, deploy |
| M2 (in progress on `v2`) | Full ads (1–5 scenes, continuous or separate shots): voiceover, captions, music, end card, every shape; themes; History; Sentry; cleanup cron |
| M3 | AI judge, Hook Lab, Post Kit (texts, checklist, ZIP), ad policy check |
| M4 (MVP) | Self-fix loop, evaluation harness, model comparison, sample-product demo, public demo under limits |
| v2.1 | Performance page, Ad Review, EU rules page, Ask assistant, batch runs |

## Architecture
React/Vite frontend (Vercel) → FastAPI API (Cloud Run service) → Postgres jobs table (Neon, Frankfurt) as the queue → worker (Cloud Run Job, same image) → fal (image and video models), OpenAI (vision, text and, from M2, voice) → ffmpeg compose in the worker (M2) → private Google Cloud Storage bucket (europe-west4), served through signed expiring URLs.

Live: site https://ugc-creator-delta.vercel.app, API https://ugc-api-1002867777166.europe-west4.run.app. Locally, Docker Compose runs the same pieces with mock providers.

## History
v1 (January 2026) was a React page plus an n8n workflow (GPT-4o → Flux Schnell → Kling → Gmail) reached through an ngrok tunnel, deployed at ugc-creator-delta.vercel.app (Vercel project `ugc-creator`). It depended on a laptop running n8n, never delivered an email to the user, and lost the real product because its image step was text-to-image. It is kept, sanitised, in `legacy/n8n/`; its code is tagged `v1-final`, and screenshots of the site are in `docs/before-after/v1/`. The v1 build stays online at https://ugc-creator-4a20yqpyc-aimilios-projects-21450502.vercel.app, linked next to v2 at the top of the README. v2 replaced it in production on 19 Nov 2026; the v2 landing page later took the v1 look with v2's own example scenes (D24).

## Out of scope
Pasting a shop link, virtual creators, many languages, direct posting to TikTok/Instagram, live ad-platform APIs. See [roadmap.md](roadmap.md).
