# End-to-end tests (Selenium + pytest)

These tests drive the real SoundPrint frontend and backend in a real Chrome browser, the way a player would.
They fill the gap between the existing unit, API and component tests, none of which run the frontend and backend together.

## How it works

- **Selenium** controls the browser: open a page, type, click, read what is on screen.
- **pytest** finds and runs the tests, checks the assertions and reports failures.
- `conftest.py` starts three servers once per run and gives each test a fresh Chrome:
  1. `fake_upstream.py` - a tiny fake of Spotify and ReccoBeats with a fixed catalog (one band with four albums), so runs are deterministic and need no credentials.
  2. The real backend, started by `run_backend.py`, which points the backend's hardcoded Spotify and ReccoBeats URLs at the fake. No production code changes.
  3. The real frontend, built and served with `next build` and `next start`.
- Tests use the **Page Object pattern** (`pages/`): selectors and page actions live in one place, so tests read like user stories.
- Waits are explicit (`WebDriverWait`), never `sleep`.
- The game picks its target album at random, so tests read the target from the backend's SQLite database (the `target_album` fixture).
- A failing test saves a screenshot to `e2e/screenshots/`.

## Running

Requires Python 3.11+, Node 20+ and Chrome.
Ports 3000, 8000 and 9100 must be free.
Selenium downloads a matching chromedriver automatically on first run, which needs network access once.

```bash
cd e2e
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend && npm install && cd ../e2e   # first time only

pytest                # headless
pytest --headed       # watch the browser
pytest -m smoke       # only the fastest checks
E2E_SKIP_BUILD=1 pytest   # reuse an existing frontend build
```

The frontend build bakes in the test backend URL, so leave `E2E_SKIP_BUILD` unset unless the last build came from this suite.

## Test layers in this repo

| Layer | Where | Tools |
|---|---|---|
| Unit | `backend/tests`, `frontend/app/GameChart.test.tsx` | pytest, Vitest |
| API / integration | `backend/tests/test_game_endpoint.py` | pytest, respx |
| Component | `frontend/app/page.test.tsx` | Vitest, React Testing Library |
| End to end | `e2e/` | Selenium, pytest |

## Not covered (possible next steps)

Cross-browser runs, Selenium Grid, CI wiring and visual regression.
