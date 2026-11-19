# UGC Ad Builder — App Overview

## What it is
A studio that turns one product photo and a short brief into a finished, ready-to-post video ad in the user-generated-content (UGC) style, with everything a marketer needs to publish it, and then measures how the ad performs.

**One line:** product photo + brief in → storyboard you approve → a video ad that keeps your real product in every frame, with the cost of every step shown.

## Who it's for
Small brands and marketers who need short social video ads (TikTok, Instagram Reels, YouTube Shorts, Facebook) without a shoot. There is no sign-in: each browser sees only the ads it created.

## Core ideas
- **The real product stays in the ad.** The uploaded photo is edited into each scene (image editing, not text-to-image), and each scene image is animated (image-to-video).
- **Nothing paid runs before approval.** The AI writes a 3-scene storyboard (hook, demo, call to action) with three hook ideas; the user edits and approves it first.
- **Cost is known and capped.** Every paid step is estimated from one price table, checked against a per-ad cap and a daily limit, and shown live in euros.
- **Measured, not asserted** (from M3–M4): an AI judge scores images and clips, self-fix retries are counted, and the evaluation harness gates changes in CI.

## The flow
Brief → Storyboard → Generate → Review → Launch kit → Performance. Milestones add the later steps:

| Milestone | What ships |
| --- | --- |
| M1 | Brief, storyboard, approval, scene 1 image + video, cost cap, privacy notice, CI, deploy |
| M2 | Full 3-scene ads: voiceover, captions, music, end card, ratios; themes; History; Sentry; cleanup cron |
| M3 | AI judge, Hook Lab, Post Kit (texts, checklist, ZIP), ad policy check |
| M4 (MVP) | Self-fix loop, evaluation harness, model comparison, sample-product demo, public demo under limits |
| v2.1 | Performance page, Ad Review, EU rules page, Ask assistant, batch runs |

## Architecture
React/Vite frontend (Vercel) → FastAPI API (Cloud Run service) → Postgres jobs table (Neon, Frankfurt) as the queue → worker (Cloud Run Job, same image) → fal (image and video models), OpenAI (vision and text) → private Google Cloud Storage bucket (europe-west4), served through signed expiring URLs.

Locally, Docker Compose runs the same pieces with mock providers.

## History
v1 (January 2026) was a React page plus an n8n workflow (GPT-4o → Flux Schnell → Kling → Gmail) reached through an ngrok tunnel, deployed at ugc-creator-delta.vercel.app (Vercel project `ugc-creator`). It depended on a laptop running n8n, never delivered an email to the user, and lost the real product because its image step was text-to-image. It is kept, sanitised, in `legacy/n8n/`. v2 is the rebuild.

## Out of scope
Pasting a shop link, virtual creators, many languages, direct posting to TikTok/Instagram, live ad-platform APIs. See [roadmap.md](roadmap.md).
