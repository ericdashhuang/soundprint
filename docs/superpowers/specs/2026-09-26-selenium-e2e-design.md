# Selenium end-to-end suite for SoundPrint

## Goal

Add a small Selenium and pytest end-to-end suite that drives the real SoundPrint frontend and backend in a real browser.
The suite fills the one gap in the current test pyramid: unit, API and component tests exist, but nothing exercises the frontend and backend together.
It is also a learning and portfolio project, so it should be small, readable and show standard QA practice rather than maximize coverage.

## Decisions already made

- Language and runner: Python with pytest and Selenium 4 (Selenium Manager fetches the driver, no manual chromedriver).
- Target: a local copy of the app, never the live demo.
- Upstream data: a fake Spotify and ReccoBeats server, so no credentials are needed and runs are deterministic.
- Base: the current `origin/main` (PR #14), on branch `test/selenium-e2e`.
- Delivery: open a PR when the suite passes. Merging happens only after the captain says so.

## Non-goals

- Selenium Grid, cross-browser runs, CI wiring, visual regression.
- Re-testing logic already covered by backend and frontend unit tests (album filtering, vibe pipeline, rate limiting).
- Any production behavior change. A production edit is allowed only as a minimal `data-testid` attribute, and each one is called out in the PR.

## Layout

A new top-level `e2e/` folder, isolated from `backend/` and `frontend/`:

```
e2e/
  README.md
  requirements.txt
  conftest.py            session fixtures (servers) and per-test fixtures (browser)
  fake_upstream.py       FastAPI app faking Spotify and ReccoBeats
  run_backend.py         test-only launcher for the real backend
  pages/                 Page Objects: landing, round, reveal
  tests/                 test_search.py, test_round.py, test_reveal.py
```

## Test stack

Three processes start once per pytest session and stop at the end:

1. Fake upstream on port 9100.
2. The real backend on port 8000.
3. The real frontend on port 3000, built with `next build` and served with `next start` (faster and steadier than `next dev`), with `NEXT_PUBLIC_API_BASE_URL` pointing at the backend.

`run_backend.py` imports the backend, overrides the hardcoded module constants `spotify_client.TOKEN_URL`, `spotify_client.API_BASE` and `reccobeats_client.BASE_URL` to point at the fake upstream, then starts uvicorn.
Those constants are read at call time, so no production code changes.
The backend runs with `DATABASE_URL` set to a temporary SQLite file, `WARM_UP_ON_STARTUP=false`, and dummy Spotify credentials.

A per-test fixture starts a fresh Chrome and quits it afterward, even when the test fails.
Chrome is headless by default, and `--headed` shows the window.

## Fake upstream data

A fixed catalog: one artist with four studio albums, each with a fixed tracklist and fixed vibe numbers (full data for every track so the target never rerolls).
It implements only the endpoints the backend actually calls (token, artist search, artist albums, album tracks, and the two ReccoBeats routes), and is checked against the request shapes in `spotify_client.py` and `reccobeats_client.py`.

## Determinism

The backend picks the target album at random.
Tests learn the target by reading the newest `GameRound` row (`target_album_id`) from the temporary SQLite file, through a small helper in `conftest.py`.
This needs no production change and no reliance on shuffle order.

## Selenium practices shown

- Page Object Model: selectors and page actions live in `pages/`, tests read as user stories.
- Explicit waits with `WebDriverWait` and expected conditions, never `time.sleep`.
- Selectors prefer the app's existing ARIA attributes (`role="option"`, `aria-label="Artist name"`, `role="alert"`, `role="tab"`) and `data-testid="game-chart"`.
- A screenshot saved on test failure, via a pytest hook.
- pytest markers so `pytest -m smoke` runs only the fastest checks.

## Tests

1. Typing an artist name shows autocomplete suggestions. (smoke)
2. Picking a suggestion starts a round showing the chart and the metric glossary. (smoke)
3. A wrong guess eliminates that album and reveals one more metric.
4. Earlier eliminations persist after further wrong guesses.
5. A correct guess shows the reveal state with the track names.
6. Giving up shows the reveal state.
7. An unknown artist shows an error alert.

The exact selectors and copy are confirmed against the running app during implementation.

## Risks

- Sparse test hooks: if an element cannot be selected reliably, add a `data-testid` and note it in the PR.
- Startup time: the frontend build adds tens of seconds to the first run, so servers start once per session, not per test.
- Port collisions: the fixtures fail fast with a clear message if 3000, 8000 or 9100 is already in use.
- Environment: Docker is not installed on this machine, which is why the suite uses SQLite instead of Postgres.

## Success criteria

- `pytest` from `e2e/` passes locally with no Spotify credentials and no network.
- Each test fails when the behavior it covers is broken (checked by deliberately breaking one behavior and seeing the test go red).
- `e2e/README.md` explains how to run it and the concepts used, well enough to talk through in an interview.
