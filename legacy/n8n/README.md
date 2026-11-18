# v1: n8n workflow (legacy)

`ugc-ad-builder-workflow-v1.json` is the original January 2026 prototype: an n8n workflow (GPT-4o → Flux Schnell → Kling → Gmail) called by the React form through an ngrok tunnel. It is kept for reference only. v2 replaces it with a Python backend (see `docs/plan/ugc-v2-full-plan.md`).

## Sanitised

The file was sanitised before it moved here. It contains placeholders instead of real values:

| Placeholder | Was |
| --- | --- |
| `Key YOUR_FAL_KEY` | a fal API key (revoked) |
| `you@example.com` | a hard-coded recipient address |
| `REPLACE_ME` | n8n credential IDs |
| `REPLACE_WITH_FOLDERID` | Google Drive folder ID |

n8n instance, workflow, version and webhook IDs were removed. To import it, add your own credentials in n8n.

## Known problems (not fixed in v1)

- The form's email field is never read; the Gmail node's recipient is hard-coded.
- The frontend posts to the `/webhook-test/` path, which only listens while the n8n editor is open.
- Flux Schnell is text-to-image, so the real product never appears in the ad.
- `image_prompt` vs `prompt` schema mismatch; the Video Prompt Generator has no system message; ratio and platform are never sent to fal; Kling is called synchronously; the Kling URL has a trailing newline.
- The sticky notes mention NanoBanana and Veo 3.1, but the nodes use Flux and Kling.

The workflow screenshot is at `frontend/public/assets/workflow-screenshot.png`.
