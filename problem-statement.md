# Problem statement

Short-form social video ads in the UGC style (a phone-camera look, a quick hook, a product shown in use) perform well, but each one needs a shoot, an editor and several variants to test. Small brands cannot produce them at the pace platforms reward.

AI image and video models can now make convincing footage, but a naive pipeline has three problems:

1. **The product drifts.** Text-to-image models invent a lookalike; the brand's real packaging, logo and text disappear.
2. **Cost is invisible.** Video models bill per second; retries and variants add up, and a loop can drain an account.
3. **Quality is asserted, not measured.** Without checks, a bad render ships, and claims in the script (invented testimonials, prices, results) create legal risk under EU advertising rules.

## What v2 must do
- Keep the real product: edit the uploaded photo into each scene, then animate that image.
- Put a human gate before any paid render: the user approves the storyboard.
- Know the cost before and after every step, cap it per ad and per day, and show it in euros.
- Measure quality with code checks and a calibrated AI judge, and gate changes in CI.
- Run as a deployed service (not a laptop with a tunnel), keep each user's ads private, and delete them on request.

## Constraints
- Budget: about 26 EUR of API spend for the whole project; all development and CI run on mock providers.
- Time: six weekly milestones of 15–20 hours, MVP at the end of M4.
- EU hosting for data at rest (Neon Frankfurt, Google Cloud europe-west4).
