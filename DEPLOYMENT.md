# Deploying to Render

`render.yaml` at the repo root is a Render Blueprint.
It already defines the backend web service and the frontend web service, and how they're wired together.
The Postgres database is hosted separately on [Neon](https://neon.com)'s free plan, because Render's free Postgres is deleted 30 days after creation.
This doc covers only what the blueprint cannot automate: creating a Render account, creating the Neon database, applying the blueprint, and supplying secrets.

## 1. Connect the repo

1. Sign in (or sign up) at [dashboard.render.com](https://dashboard.render.com).
2. Click **New > Blueprint**.
3. Connect your GitHub account if you haven't already, then select `ericdashhuang/soundprint`.
4. Render reads `render.yaml` and shows a preview of the two resources it will create: `album-flow-backend` and `album-flow-frontend`.

## 2. Apply the blueprint

Click **Apply**. Render builds and deploys both services.

## 3. Fill in the database URL and the two Spotify secrets

`render.yaml` marks `DATABASE_URL`, `SPOTIFY_CLIENT_ID`, and `SPOTIFY_CLIENT_SECRET` as `sync: false`, so Render prompts for them during apply (or you can set them afterward under `album-flow-backend` > **Environment**).

For `DATABASE_URL`, create a free project at [console.neon.tech](https://console.neon.tech) and copy its pooled connection string (`neon connection-string --pooled` from the Neon CLI prints it).
The backend creates its tables on startup, so an empty database is fine.

Get real values from a Spotify developer app at <https://developer.spotify.com/dashboard> (Client Credentials flow only - no redirect URI or user login needed).
Without real values the backend still boots, but any Spotify-backed request fails with a 502.

## 4. Confirm the deploy

Once both services show **Live**:

- Open the backend's health check: `https://album-flow-backend.onrender.com/api/health` should return `{"status": "ok"}`.
- Open the frontend at `https://album-flow-frontend.onrender.com` and start a round to confirm it can reach the backend (check the browser console/network tab if it can't).

## Notes and caveats

- **Neon's free plan scales the database to zero when idle.** The first query after a quiet period takes a moment longer while it wakes; there is no expiry.
- **Free-tier web services sleep.** Both services are on the `free` plan, which spins down after 15 minutes of inactivity; the first request after a period of idleness will be slow while it spins back up. Upgrade the plan on either service if that's not acceptable. Free instance hours (750/month) are shared across the whole Render workspace, which is why `.github/workflows/keep-backend-warm.yml` is disabled in GitHub: pinging the backend around the clock alone would use almost all of them.
- **Cross-service URLs are hardcoded, not templated.** Render's blueprint `fromService` reference only exposes a service's private-network host/port, not its public URL, so `render.yaml` hardcodes each service's `https://<name>.onrender.com` URL for the other to call/CORS-allow. If you rename `album-flow-backend` or `album-flow-frontend`, or attach a custom domain to either, update `CORS_ORIGINS` and `NEXT_PUBLIC_API_BASE_URL` in `render.yaml` (or directly in the dashboard) to match.
