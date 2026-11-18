# Feedback notes

Findings from real use and testing, by round. Each finding that changes the product gets a decision in [DECISIONS.md](DECISIONS.md).

## Round 0 — audit of v1 (17–18 Nov 2026)
- The fal key and a personal email address were hard-coded in the public workflow file. → Step 0, [D5](DECISIONS.md).
- The form's email field was never read; the frontend posted to the test-only webhook path. → v2 rebuild.
- Text-to-image lost the real product. → image editing from the uploaded photo, [D10](DECISIONS.md).
- The landing page showed invented statistics. → honest landing page (M1).

## Round 1 — M1 live smoke test
*(to be filled after the first real run on the deployed site)*
