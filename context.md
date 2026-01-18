# UGC Ad Builder - Project Context

## Project Overview
The UGC Ad Builder is a comprehensive system designed to automate the creation of User-Generated Content (UGC) style ads. It consists of a high-end, premium React frontend and a robust n8n automation workflow backend.

## Live Deployment

### Production URLs
- **Frontend (Vercel)**: https://ugc-creator-delta.vercel.app
- **GitHub Repository**: https://github.com/Aimilios94/UGC-Creator
- **n8n Webhook (via ngrok)**: https://subalternate-presumptively-breanna.ngrok-free.dev/webhook/ugc-ad-trigger

### Accounts & Services
- **GitHub Account**: Aimilios94 (for Vercel deployment)
- **Vercel Project**: ugc-creator
- **ngrok Account**: Aimilios94 (free tier)

## Architecture

### 1. Frontend (React + Vite)
- **Location**: `/frontend`
- **Tech Stack**:
  - Framework: React 19.2 with Vite 7.2
  - Styling: Vanilla CSS with CSS Variables for theme management
  - Icons: Lucide-React
  - Animation: Framer Motion + CSS transitions and keyframes
- **Core Components**:
  - `Hero.jsx`: Premium entry section with moving thumbnails and gradient typography.
  - `Samples.jsx`: Grid showcase of AI-generated UGC examples with performance metrics.
  - `BuilderForm.jsx`: The main interaction point. Features drag-and-drop file upload, advanced ad parameter selection (Platform, Ad Type, Tone, Aspect Ratio), and real-time form validation.
- **Key Features**:
  - **Local Asset Hosting**: All UI assets (Samples/Hero thumbnails) are served locally from `frontend/public/assets`.
  - **Webhook Integration**: Submits multipart `FormData` (including images) to n8n via ngrok tunnel.
  - **State Management**: Handles complex loading states, submission errors, and success flow transitions.

### 2. Backend (n8n Workflow)
- **File**: `UGC Ad Builder Workflow.json`
- **Status**: Active and configured with all credentials
- **Workflow Steps**:
  1. **Webhook Trigger**: Receives binary image data and metadata (description, platform, tone, ratio) from the frontend via `POST /ugc-ad-trigger`.
  2. **Analysis & Archival** (Parallel):
     - **Google Drive**: Uploads the raw user asset to a specific folder for archival.
     - **Image Analysis**: Uses an AI Agent (OpenAI GPT-4o) to generate a detailed description of the product or character in the uploaded image.
  3. **Visual Synthesis**:
     - **Image Prompt Generation**: An AI Agent constructs a highly detailed "UGC-style" image prompt based on the analysis and user concept.
     - **Image Generation**: Calls `fal.ai/flux/schnell` to generate a high-quality base image.
  4. **Video Creation**:
     - **Video Prompt Generation**: An AI Agent creates a motion prompt, combining the generated image URL with the user's concept, tone, and platform requirements.
     - **Video Generation**: Calls `fal.ai/kling-video/v1/standard/image-to-video` to animate the generated image into a video.
  5. **Delivery**:
     - **Gmail**: Sends the final video URL directly to the user's email address.

### 3. n8n Credentials Configured
- OpenAI API (GPT-4o for analysis and prompt generation)
- Google Drive OAuth (asset archival)
- Gmail OAuth (video delivery)
- Header Auth (Fal.ai API for image/video generation)

### 4. Environment Variables
- **Vercel**: `VITE_N8N_WEBHOOK_URL` = ngrok tunnel URL + `/webhook/ugc-ad-trigger`
- **Local**: `/frontend/.env` with webhook URL

## Implementation Progress

### Completed Tasks
- [x] Initial n8n workflow design and JSON export
- [x] Frontend scaffolding with Vite and React
- [x] Design system implementation (Dark mode, premium aesthetics)
- [x] Hero and Samples sections with real AI-generated image assets
- [x] BuilderForm with drag-and-drop and configuration selectors
- [x] Submission Logic: Connected the form to the n8n webhook with full `FormData` support
- [x] UI Polish: Implemented loading spinners, success messaging, and form reset capabilities
- [x] Workflow Refinement: Finalized `UGC Ad Builder Workflow.json` with Flux Schnell (Images) and Kling (Video) via Fal.ai
- [x] **GitHub Repository**: Created and pushed to Aimilios94/UGC-Creator
- [x] **Vercel Deployment**: Frontend deployed at https://ugc-creator-delta.vercel.app
- [x] **README Enhancement**: Added badges, architecture diagram, tech stack tables, and comprehensive documentation
- [x] **MIT License**: Added LICENSE file
- [x] **ngrok Setup**: Configured tunnel for n8n webhook access
- [x] **Environment Variables**: Configured VITE_N8N_WEBHOOK_URL in Vercel

### Current Configuration
- **Frontend URL (Production)**: https://ugc-creator-delta.vercel.app
- **Frontend URL (Local)**: http://localhost:5173
- **Webhook Endpoint (Production)**: https://subalternate-presumptively-breanna.ngrok-free.dev/webhook/ugc-ad-trigger
- **Webhook Endpoint (Local)**: http://localhost:5678/webhook-test/ugc-ad-trigger
- **Asset Directory**: `frontend/public/assets/`

## Running the Project

### Local Development
1. **Start n8n**:
   ```bash
   npx n8n
   ```

2. **Start ngrok** (in separate terminal):
   ```bash
   cd C:\ngrok
   ngrok http 5678
   ```

3. **Start frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

### Production
- Frontend auto-deploys from GitHub via Vercel
- n8n must be running locally with ngrok tunnel active
- Update Vercel environment variable if ngrok URL changes

## Important Notes

### ngrok Free Tier Limitations
- URL changes every time ngrok is restarted
- When URL changes, update `VITE_N8N_WEBHOOK_URL` in Vercel and redeploy
- Consider upgrading to ngrok paid plan for static URL, or migrate to n8n Cloud

### For Permanent Deployment
To avoid ngrok URL changes, consider:
1. **n8n Cloud**: https://n8n.io/cloud - hosted n8n with permanent URLs
2. **Self-hosted n8n**: Deploy on VPS (DigitalOcean, Hetzner, etc.) with fixed domain
3. **ngrok Paid Plan**: Get a static subdomain

## Design Principles
- **Clean & Premium**: High contrast, generous whitespace, and subtle gradients
- **Interactive**: Hover states, smooth animations, and clear feedback loops (Loading/Success)
- **Responsive**: Mobile-first grid layouts for the form and gallery
- **Dark Mode**: Native dark theme with glassmorphism effects

## Project Structure
```
UGC-Ad-Builder/
├── frontend/                    # React + Vite frontend
│   ├── src/
│   │   ├── components/         # Hero, Samples, BuilderForm
│   │   ├── styles/             # Global CSS + Variables
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── public/
│   │   └── assets/             # Sample images
│   ├── .env                    # Environment variables
│   ├── package.json
│   └── vite.config.js
│
├── UGC Ad Builder Workflow.json # n8n workflow (import this)
├── context.md                   # Project documentation (this file)
├── CLAUDE.md                    # AI assistant guidelines
├── README.md                    # Public repository README
└── LICENSE                      # MIT License
```
