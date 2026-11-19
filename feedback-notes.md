# Feedback notes

Findings from real use and testing, by round. Each finding that changes the product gets a decision in [DECISIONS.md](DECISIONS.md).

## Round 0 — audit of v1 (17–18 Nov 2026)
- The fal key and a personal email address were hard-coded in the public workflow file. → Step 0, [D5](DECISIONS.md).
- The form's email field was never read; the frontend posted to the test-only webhook path. → v2 rebuild.
- Text-to-image lost the real product. → image editing from the uploaded photo, [D10](DECISIONS.md).
- The landing page showed invented statistics. → honest landing page (M1).

## Round 1 — M1 live smoke test (18 Nov 2026)
- The full leg works on the deployed stack: storyboard in about 35 s, image and video in about 2 min, the job finished with the browser closed. Real recorded cost 0.3425 EUR (estimate 0.3391 EUR + 0.003 EUR of LLM).
- Product fidelity is good on text and shape; the bottle's colour drifted lighter and more translucent. → input for the M3 judge rubric (colour fidelity).
- The storyboard step takes about 35 s with a spinner and no progress detail. → consider a progress hint in the Brief step (M2 polish).
- The landing page's sample images all show people, and `frontend/public/assets/user_upload.png` was a browser screenshot, not a product (deleted). → seeded demo ads replace the samples in M4; until then the landing page shows example scenes in the v1 look (D24, 19 Nov 2026).
- **Owner's manual test on the v2 preview** (18 Nov 2026): the job finished, the video plays, 0.34 EUR shown against the cap. fal Usage matched the price table (about 0.78 USD for both runs together). The on-screen text in the generated scene came out **garbled** (AI-rendered lettering). → the M3 judge must score packaging and on-screen text fidelity and catch this; captions should be burned in by `compose.py` (M2), never left to the model.
- Production check after the merge (19 Nov 2026): the site is v2, it reaches the API, CORS allows it, and the access-code gate refuses a wrong code.
