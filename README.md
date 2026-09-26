# SoundPrint

**Live demo:** https://album-flow-frontend.onrender.com

An artist album-guessing game.
Type an artist's name and the app secretly picks one of their real albums.
Each wrong guess eliminates an album and reveals one more per-track audio metric as a chart line; a correct guess reveals the track names and a glossary of every metric.

## Project structure

- `backend/` - FastAPI service that talks to the Spotify Web API (Client Credentials flow, app-level auth only, no user login), orchestrates each round server-side (`app/game_service.py`), computes a per-track vibe score for each metric (primarily via ReccoBeats, falling back to 30-second preview clips plus librosa when ReccoBeats has no match), and exposes the `/api/game/*` endpoints.
- `frontend/` - Next.js (App Router) app: an artist search box, a chart (`GameChart.tsx`) that reveals one metric line at a time as guesses go wrong, and a metric glossary (`MetricGlossary.tsx`) shown from round start.
- `docker-compose.yml` - local Postgres for backend development.
- `render.yaml` - Render Blueprint for deploying both services plus a managed Postgres database. See `DEPLOYMENT.md` for the remaining manual steps.

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker (for local Postgres), or any Postgres instance you point `DATABASE_URL` at.
- A Spotify developer app.
Create one at https://developer.spotify.com/dashboard to get a real `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`.
Until you have real credentials, the backend runs fine with the placeholder values in `.env.example` - starting a round against real Spotify data will just fail with a 502 until real credentials are set.

## Running the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# Edit .env with real Spotify credentials once you have a developer app.

# Start a local Postgres (from the repo root):
docker compose up -d postgres

uvicorn app.main:app --reload --port 8000
```

The API is now at `http://localhost:8000`.
Interactive docs are at `http://localhost:8000/docs`.

Run the backend test suite (no live Spotify or ReccoBeats calls; all HTTP calls are mocked):

```bash
cd backend
pytest
```

## Running the frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

The app is now at `http://localhost:3000`.
It expects the backend to be running at the URL in `NEXT_PUBLIC_API_BASE_URL` (`http://localhost:8000` by default).

Run the frontend test suite (Vitest + React Testing Library):

```bash
cd frontend
npm test
```

Run the end-to-end browser tests (Selenium + pytest, against a fake Spotify server; see `e2e/README.md`):

```bash
cd e2e
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

## Tech stack

- **Backend**: Python, FastAPI, SQLModel, Postgres (SQLite in-memory for tests).
- **Frontend**: TypeScript, Next.js (App Router), Recharts.
- **Deployment**: Render, via the `render.yaml` Blueprint.

## Known constraints

- No user login: every visitor plays against the same server-side game state, resolved by artist name/ID against public Spotify catalog data.
Spotify's Development Mode quota for new apps makes a personalized-login flow impractical for a solo project, so the app authenticates to Spotify only at the app level (Client Credentials flow).
- Spotify's `audio-features`/`audio-analysis` endpoints are gone for apps registered after 2024-11-27, so per-track vibe metrics come from ReccoBeats (a free, keyless third-party API keyed by Spotify track ID - see `backend/app/reccobeats_client.py`) as the primary source, with 30-second-preview-clip-plus-librosa analysis (`backend/app/vibe_analysis.py`) kept as a fallback for whenever ReccoBeats has no data for a track.
ReccoBeats is primary because a track's `preview_url` has turned out to be null far more often in practice than originally assumed - real-world testing across several major albums found zero available preview clips - so the preview-dependent path alone is not a reliable primary source.
See the docstring at the top of `backend/app/reccobeats_client.py` for the exact API contract and field-mapping rationale, and `backend/app/vibe_analysis.py` for why librosa was used for the fallback instead of Essentia's pretrained mood classifiers.
- If both ReccoBeats and the preview+librosa fallback come up empty for a track, that track's `vibe` is `null` in the API response instead of failing the round.
- Computed vibes are cached in Postgres by Spotify track ID (`TrackVibe` in `backend/app/models.py`), so the same track is never re-analyzed across different albums or rounds, regardless of which source produced it.
- Round state (the secret target album, its track names, and the cumulative list of wrong-guessed albums) is held server-side in the `GameRound` table and is server-authoritative: no in-progress-round API response ever includes the target's identity or a track name.
