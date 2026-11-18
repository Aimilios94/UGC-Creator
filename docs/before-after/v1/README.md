# v1 site, before M1

Full-page screenshots of the production site (https://ugc-creator-delta.vercel.app) as it was on 18 Nov 2026, before the M1 merge replaced it with v2. They are kept for a before/after comparison.

| File | View |
| --- | --- |
| `v1-desktop-full.png` | 1440 px wide |
| `v1-mobile-full.png` | 390 px wide |

## Still viewable
- This exact build stays online at its permanent Vercel deployment URL: https://ugc-creator-4a20yqpyc-aimilios-projects-21450502.vercel.app (production deployment of `main` at `2404369`, the v1 frontend).
- The code is tagged `v1-final` (GitHub release "v1 — n8n prototype").

## Known issues visible here
From the v2 audit (plan §3):
- **Invented numbers:** "10x faster creation", "95% higher engagement", "50k+ ads created", and the views, likes and CTR on the sample cards were never measured.
- **Wrong models named:** the badge says "Powered by Gemini 3.0, n8n, NanoBanana, and Veo3.1"; the workflow actually used GPT-4o, Flux Schnell and Kling.
- **Buttons do nothing:** "Start Creating Free" and "View Examples" have no handlers.
- **The form never delivered:** it posted to n8n's test-only webhook on `localhost`, the email field was never read, and the recipient was hard-coded. No user ever received a video.
- **The real product was lost:** the image step was text-to-image, so the uploaded product never appeared in the ad.
- **Other:** the page title is "frontend"; there is no file validation, job status or result page; sample images show people, with no consent or AI-label notice.

v2 (M1) fixes these: see [CHANGELOG.md](../../../CHANGELOG.md) and [docs/notes/m1-secure-base.md](../../notes/m1-secure-base.md).
