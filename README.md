<p align="center">
  <img src="https://img.shields.io/badge/React-19.1-61DAFB?style=for-the-badge&logo=react&logoColor=white" alt="React" />
  <img src="https://img.shields.io/badge/Vite-6.3-646CFF?style=for-the-badge&logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/n8n-Workflow-EA4B71?style=for-the-badge&logo=n8n&logoColor=white" alt="n8n" />
  <img src="https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=for-the-badge&logo=openai&logoColor=white" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Fal.ai-Flux%20%2B%20Kling-FF6B6B?style=for-the-badge" alt="Fal.ai" />
</p>

<h1 align="center">UGC Ad Builder</h1>

<p align="center">
  <strong>AI-powered UGC (User-Generated Content) ad creation platform</strong><br/>
  Upload your product images, define your ad concept, and receive a fully generated video ad via email.
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#demo">Demo</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#getting-started">Getting Started</a> •
  <a href="#deployment">Deployment</a> •
  <a href="#license">License</a>
</p>

---

## Features

| Feature | Description |
|---------|-------------|
| **Drag & Drop Upload** | Easy file upload for product images with visual preview |
| **Multi-Platform Support** | TikTok, Instagram Reels, YouTube Shorts, Facebook Ads |
| **AI Image Analysis** | Automatic product/character detection using GPT-4o |
| **AI Image Generation** | Creates UGC-style images with Flux Schnell via Fal.ai |
| **AI Video Generation** | Animates images into videos using Kling Video via Fal.ai |
| **Email Delivery** | Receive your finished video directly in your inbox |
| **Premium UI** | Dark mode, glassmorphism effects, responsive design |

## Demo

<p align="center">
  <img src="frontend/public/assets/skincare.png" width="200" alt="Skincare Demo"/>
  <img src="frontend/public/assets/tech.png" width="200" alt="Tech Demo"/>
  <img src="frontend/public/assets/fashion.png" width="200" alt="Fashion Demo"/>
</p>

## Tech Stack

### Frontend
| Technology | Purpose |
|------------|---------|
| ![React](https://img.shields.io/badge/React-61DAFB?style=flat-square&logo=react&logoColor=black) | UI Framework |
| ![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white) | Build Tool & Dev Server |
| ![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=flat-square&logo=css3&logoColor=white) | Styling with CSS Variables |
| ![Lucide](https://img.shields.io/badge/Lucide-F56565?style=flat-square) | Icon Library |

### Backend (n8n Workflow)
| Technology | Purpose |
|------------|---------|
| ![n8n](https://img.shields.io/badge/n8n-EA4B71?style=flat-square&logo=n8n&logoColor=white) | Workflow Automation |
| ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat-square&logo=openai&logoColor=white) | Image Analysis & Prompt Generation |
| ![Fal.ai](https://img.shields.io/badge/Fal.ai-FF6B6B?style=flat-square) | Image & Video Generation |
| ![Google Drive](https://img.shields.io/badge/Google%20Drive-4285F4?style=flat-square&logo=googledrive&logoColor=white) | Asset Archival |
| ![Gmail](https://img.shields.io/badge/Gmail-EA4335?style=flat-square&logo=gmail&logoColor=white) | Video Delivery |

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              USER                                        │
│                    Uploads Image + Defines Concept                       │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         REACT FRONTEND                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────────┐  │
│  │    Hero     │  │   Samples   │  │         BuilderForm             │  │
│  │  Component  │  │   Gallery   │  │  • Drag & Drop Upload           │  │
│  │             │  │             │  │  • Platform/Tone Selection      │  │
│  │             │  │             │  │  • Webhook Submission           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ POST /webhook
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          N8N WORKFLOW                                    │
│                                                                          │
│  ┌──────────┐    ┌──────────────────────────────────────────────────┐   │
│  │ Webhook  │───▶│              PARALLEL PROCESSING                  │   │
│  │ Trigger  │    │  ┌─────────────┐       ┌─────────────────────┐   │   │
│  └──────────┘    │  │Google Drive │       │  OpenAI GPT-4o      │   │   │
│                  │  │  (Archive)  │       │  (Image Analysis)   │   │   │
│                  │  └─────────────┘       └──────────┬──────────┘   │   │
│                  └───────────────────────────────────┼──────────────┘   │
│                                                      ▼                   │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    IMAGE GENERATION PIPELINE                       │  │
│  │  ┌─────────────────┐         ┌─────────────────────────────────┐  │  │
│  │  │ OpenAI GPT-4o   │────────▶│  Fal.ai Flux Schnell            │  │  │
│  │  │ (Prompt Gen)    │         │  (Image Generation)             │  │  │
│  │  └─────────────────┘         └───────────────┬─────────────────┘  │  │
│  └──────────────────────────────────────────────┼────────────────────┘  │
│                                                 ▼                        │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    VIDEO GENERATION PIPELINE                       │  │
│  │  ┌─────────────────┐         ┌─────────────────────────────────┐  │  │
│  │  │ OpenAI GPT-4o   │────────▶│  Fal.ai Kling Video             │  │  │
│  │  │ (Motion Prompt) │         │  (Image-to-Video)               │  │  │
│  │  └─────────────────┘         └───────────────┬─────────────────┘  │  │
│  └──────────────────────────────────────────────┼────────────────────┘  │
│                                                 ▼                        │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                         GMAIL DELIVERY                            │   │
│  │                    Sends video URL to user                        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

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
│   ├── package.json
│   └── vite.config.js
│
├── UGC Ad Builder Workflow.json # n8n workflow (import this)
├── context.md                   # Project documentation
└── README.md
```

## Getting Started

### Prerequisites

- **Node.js** 18+
- **n8n** instance (self-hosted or cloud)
- **API Keys**: OpenAI, Fal.ai, Google OAuth, Gmail OAuth

### Frontend Setup

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend will be available at `http://localhost:5173`

### Backend Setup (n8n)

1. **Start your n8n instance**
   ```bash
   npx n8n
   ```

2. **Import the workflow**
   - Open n8n at `http://localhost:5678`
   - Go to Workflows → Import from File
   - Select `UGC Ad Builder Workflow.json`

3. **Configure credentials**
   | Credential | Purpose |
   |------------|---------|
   | OpenAI API | Image analysis & prompt generation |
   | Google Drive OAuth | Asset archival |
   | Gmail OAuth | Video delivery |
   | Fal.ai API Key | Image & video generation |

4. **Activate the workflow**
   - Toggle the workflow to "Active"
   - Note the webhook URL (update frontend `.env` if needed)

### Environment Variables

Create `frontend/.env`:

```env
VITE_N8N_WEBHOOK_URL=http://localhost:5678/webhook-test/ugc-ad-trigger
```

## Deployment

### Frontend (Vercel)

1. Push your code to GitHub
2. Import repository in [Vercel](https://vercel.com)
3. Configure:
   - **Framework Preset**: Vite
   - **Root Directory**: `frontend`
4. Add environment variables:
   - `VITE_N8N_WEBHOOK_URL` → Your production n8n webhook URL
5. Deploy

### Backend (n8n)

For production, your n8n instance must be publicly accessible:
- **n8n Cloud**: [https://n8n.io](https://n8n.io)
- **Self-hosted**: Deploy on a VPS with a public URL
- Use the **Production webhook URL** (not Test URL)

## Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Premium Aesthetics** | High contrast, generous whitespace, subtle gradients |
| **Interactivity** | Hover states, smooth animations, clear feedback |
| **Responsiveness** | Mobile-first grid layouts |
| **Dark Mode** | Native dark theme with glassmorphism effects |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/ugc-ad-trigger` | POST | Receives form data with image and parameters |

### Request Payload

```json
{
  "image": "<binary>",
  "email": "user@example.com",
  "description": "Product description and ad concept",
  "platform": "tiktok | instagram | youtube | facebook",
  "tone": "energetic | calm | professional | playful",
  "ratio": "9:16 | 1:1 | 16:9"
}
```

## Roadmap

- [ ] Multiple image upload support
- [ ] Video preview before email delivery
- [ ] Custom branding/watermark options
- [ ] Template library for different industries
- [ ] Analytics dashboard

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Made with AI by <a href="https://github.com/aimilios944">@aimilios944</a>
</p>
