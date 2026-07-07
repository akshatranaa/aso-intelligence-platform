# ASO Intelligence Platform

App Store Optimization intelligence, powered by Apple's free public APIs + AI.
Collect any iOS app from any App Store country and analyse its keyword
rankings, review sentiment, and competitors — with every country's data kept
as its own independent dataset.

**Live app:** https://aso-intelligence-platform-akshatrana.vercel.app

## Architecture

| Layer | Tech | Deploy |
|---|---|---|
| Frontend (`web/`) | Next.js 16 · TypeScript · Tailwind · TanStack Query · Recharts | Vercel (auto on push) |
| Backend (`api/`) | FastAPI · Python | Render (auto on push) |
| Database | Postgres | Neon |
| AI | Groq (`llama-3.1-8b-instant`) | — |

The browser only ever calls the Next.js app's same-origin `/api/*` routes,
which proxy to the FastAPI backend server-side (API key never reaches the
client). All analysis data is scoped by `(app_id, country)`.

## Features

- **Collect** — full pipeline per app+country: metadata, AI-judged competitor
  discovery, reviews, sentiment, keyword rank snapshots. Async job with live
  progress; re-collects within 7 days reuse the competitor set.
- **Overview** — per-country scorecards, sentiment snapshot, best ranks,
  priority actions.
- **Sentiment** — rating-first labelling (4–5★ positive, 1–2★ negative, 3★
  decided by AI/VADER), donut + rating distribution + review browser.
- **Rankings** — tracked keywords with rank/delta/velocity/trend, custom
  keyword tracking, one-click refresh, and live competitor rank comparison for
  any keyword in any country.
- **Competitors** — candidates from seed-keyword searches, gated by an AI
  relevance judge, scored by popularity, tiered.
- **Recommendations** — priority actions, keyword buckets, review themes,
  competitor advantage comparison, AI description rewrite.

## Local development

Backend (needs `.env` with `DATABASE_URL`, `GROQ_API_KEY`):

```bash
pip install -r requirements.txt
python3 -m uvicorn api.main:app --port 8001
```

Frontend (needs `web/.env.local` — see `web/.env.example`):

```bash
cd web
npm install
npm run dev   # http://localhost:3000
```

CLI collection pipeline (no server):

```bash
python3 main.py "Spotify"
```

## Environment variables

| Var | Where | Purpose |
|---|---|---|
| `DATABASE_URL` | backend | Neon Postgres connection string |
| `GROQ_API_KEY` | backend | AI features (seeds, judge, sentiment, recommendations) |
| `ASO_API_KEY` | backend + web | optional; protects POST endpoints |
| `ASO_ALLOWED_ORIGINS` | backend | optional CORS allowlist |
| `ASO_API_BASE` | web | backend base URL for the proxy |
