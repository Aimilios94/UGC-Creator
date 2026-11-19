# UGC Ad Builder — frontend

React 19 + Vite. The guided flow (Brief → Storyboard → Generate), the landing page and the privacy notice. Live at https://ugc-creator-delta.vercel.app (Vercel project `ugc-creator`, root directory `frontend`).

```bash
npm install
npm run dev      # http://localhost:5173
npm run lint
npm run build
```

- `VITE_API_BASE_URL` points at the API (default `http://localhost:8000`; see `.env.example`). `VITE_` values are public and baked in at build time: never put a secret here.
- `src/lib/api.js` is the only place that talks to the API. It sends the browser session ID (`X-Session-Id`) and the access code (`X-Access-Code`).
- Pages live in `src/pages/` (Landing, Brief, Job = Storyboard + Generate, Privacy). Routing uses the URL hash (`#/create`, `#/job/<id>`, `#/privacy`).
- Money is shown in EUR by default; USD is a display option under Advanced settings.

Full setup, the backend and the deploy: [../docs/SETUP.md](../docs/SETUP.md).
