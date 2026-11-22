# Roadmap

The milestone plan is in [docs/plan/ugc-v2-full-plan.md](docs/plan/ugc-v2-full-plan.md) §17. This file holds what comes after it.

## Now
- **M1** ✅ secure base and first pipeline leg (merged and live, 19 Nov 2026).
- **M2** (in progress on `v2`, not deployed): full ads. Done: CI on current actions and a ruleset on `main` (D23); campaign brief, brand kit and the testimonial rule (D25); compose, voice and music (D26); the user-steered storyboard, pictures then video, 1–5 scenes, video length, continuous shot and style notes (D27–D29); every scene flows into the next, also with own pictures (D30). Now: the prompt-to-ad strategy (D31, 6 phases; phase 1 done: the fixed structure, rules files, shorter clip rules, golden tests, the local findings archive; own pictures fill the frame; phase 2 done: the scene splitter for headings and lists; phase 3 done: the slot filler with "AI's guess" marks, paragraphs read into scenes, and the real-length line with "Add scenes" or "Keep"; phase 4 done: every clip built from the structure within a budget, the user's words reaching the video AI word for word, "AI changed" with Undo for Kling weak spots, and the marks editable in place; next: quick questions (phase 5), then the image path and the no-photo route (phase 6)). Then: themes, cost tracking and History, Sentry and the docs page, the cleanup cron and "delete my data", then the M2 deploy. Before M2: a landing refresh in the v1 look (D24, PR #4).
- **Before 6 Jan 2027:** replace the voice model (OpenAI shuts `gpt-4o-mini-tts` down; D26).
- Then: M3 judge + Hook Lab + Post Kit, M4 measured public MVP, then v2.1 (M5–M6).

## Later extras
- Product photo studio
- Talking presenter
- Shareable permalink
- Before/after slider
- Weekly summary PDF
- Google and YouTube CSV presets for the Performance page
- Signed content credentials (C2PA)
- Post scheduling and publishing (needs each platform's API review and a small due-posts queue on the same cron)
- Competitor ad tracker
- Social content calendar
- Comment and review sentiment
- Budget reallocation suggestions
- Live ad-platform APIs
- Email and subject-line writer
- Digital Fairness Act follow-up (M5 adds the "watching" line)
- Upload your own voice recording instead of the AI voice (asked about on 20 Nov 2026; not chosen for now)
- Pin each clip's last frame to the next scene's picture with Kling's end-frame input (separate-shots mode)

## Insights (future section)
- Performance aggregates by hook formula, theme and platform
- Creative-fatigue alerts
- "Your CTR vs typical for this theme" benchmarks
- A cross-user hook library (needs user consent)
- Possible paid ladder: usage tiers, higher-quality presets, batch volume, longer retention and history, API access, direct posting

## Future list (not in v2)
Paste a shop link, virtual creators, many languages, direct posting to TikTok/Instagram, match-data graphics, content calendar, loop-friendly cut, seasonal overlays, hook generation from competitor transcripts, native model audio.

## Future ideas
- **Design Lab (v3, not planned):** a conversational re-creation studio. Chat with ads already made ("change the hook", "make it more cinematic"), choose the model per re-creation from the model matrix, see the real cost estimate before confirming, attach reference images, and pick canvas ratio and resolution. Placeholder only: no design, tasks or milestones.
