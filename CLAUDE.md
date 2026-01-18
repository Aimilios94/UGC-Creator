# CLAUDE.md - AI Assistant Guidelines for UGC Ad Builder

## Project Summary
UGC Ad Builder is an AI-powered platform for creating User-Generated Content style video ads. Users upload product images, configure ad parameters, and receive generated video ads via email.

## Tech Stack
- **Frontend**: React 19.2 + Vite 7.2 + Vanilla CSS
- **Backend**: n8n workflow automation
- **AI Services**: OpenAI GPT-4o, Fal.ai (Flux Schnell + Kling Video)
- **Hosting**: Vercel (frontend), ngrok tunnel (n8n webhook)

## Key Files & Locations

### Frontend
- `frontend/src/components/Hero.jsx` - Landing hero section
- `frontend/src/components/Samples.jsx` - Gallery of sample ads
- `frontend/src/components/BuilderForm.jsx` - Main form component (most important)
- `frontend/src/App.jsx` - Main app component
- `frontend/src/index.css` - Global styles and CSS variables
- `frontend/public/assets/` - Image assets

### Backend
- `UGC Ad Builder Workflow.json` - n8n workflow (import into n8n)

### Configuration
- `frontend/.env` - Environment variables (VITE_N8N_WEBHOOK_URL)
- `frontend/package.json` - Dependencies and scripts
- `frontend/vite.config.js` - Vite configuration

### Documentation
- `README.md` - Public documentation with badges and setup instructions
- `context.md` - Detailed project context and architecture
- `CLAUDE.md` - This file (AI assistant guidelines)

## Common Commands

```bash
# Start frontend development server
cd frontend && npm run dev

# Build frontend for production
cd frontend && npm run build

# Start n8n locally
npx n8n

# Start ngrok tunnel (from C:\ngrok folder)
cd C:\ngrok && ngrok http 5678

# Git operations
git add . && git commit -m "message" && git push origin main
```

## Architecture Overview

```
User → Vercel Frontend → ngrok → n8n Workflow → Email
                                      ↓
                              OpenAI (analysis)
                              Fal.ai (image gen)
                              Fal.ai (video gen)
                              Google Drive (archive)
                              Gmail (delivery)
```

## Form Data Flow
1. User uploads image + fills form (email, description, platform, tone, ratio)
2. Frontend sends FormData to n8n webhook
3. n8n processes: analyze image → generate prompt → create image → create video
4. Video URL sent to user's email

## Environment Variables

### Vercel (Production)
- `VITE_N8N_WEBHOOK_URL` - Full ngrok webhook URL with path

### Local (.env)
- `VITE_N8N_WEBHOOK_URL=http://localhost:5678/webhook-test/ugc-ad-trigger`

## Styling Guidelines
- Use CSS variables defined in `index.css`
- Dark mode is default (no light mode toggle needed)
- Glassmorphism effects for cards
- Gradient text for headings
- Mobile-first responsive design

## Important Notes

### When Modifying Frontend
- Test locally with `npm run dev` before pushing
- Vercel auto-deploys on push to main branch
- Check browser console for errors

### When Modifying n8n Workflow
- Export workflow as JSON and save to `UGC Ad Builder Workflow.json`
- Keep workflow active in n8n
- Test webhook with sample data before production use

### ngrok Considerations
- Free tier URL changes on restart
- If URL changes: update Vercel env var → redeploy
- Keep ngrok terminal open during use

## Deployment Checklist

### For Frontend Changes
1. Make changes locally
2. Test with `npm run dev`
3. Commit and push to GitHub
4. Vercel auto-deploys

### For n8n Changes
1. Modify workflow in n8n UI
2. Export and save JSON
3. Ensure workflow is active

### For Full System Test
1. n8n running (`npx n8n`)
2. ngrok running (`ngrok http 5678`)
3. Correct webhook URL in Vercel
4. Submit test form on live site

## Troubleshooting

### Form submission not working
- Check if n8n is running
- Check if ngrok is running
- Verify webhook URL in Vercel matches ngrok URL
- Check browser Network tab for errors

### Video not received
- Check n8n execution logs
- Verify Gmail credentials in n8n
- Check spam folder

### Build failing on Vercel
- Check `frontend/` is set as root directory
- Verify Vite framework preset is selected
- Check build logs for specific errors

## API Endpoints

### Webhook (n8n)
- **URL**: `{ngrok-url}/webhook/ugc-ad-trigger`
- **Method**: POST
- **Content-Type**: multipart/form-data
- **Fields**: image (file), email, description, platform, tone, ratio

## Future Improvements (Roadmap)
- [ ] Multiple image upload support
- [ ] Video preview before email delivery
- [ ] Custom branding/watermark options
- [ ] Template library for different industries
- [ ] Analytics dashboard
- [ ] Migrate to n8n Cloud for permanent URL
