"""test only launcher for the real soundprint backend

the backend hardcodes the spotify and reccobeats urls as module constants that
are read at call time, this launcher repoints them at the fake upstream and
then starts the unmodified backend app with uvicorn, so no production code
has to change for the end to end tests

usage python run_backend.py <port>
environment FAKE_UPSTREAM_URL (eg http://127.0.0.1:9100), plus the usual
backend settings (DATABASE_URL, SPOTIFY_CLIENT_ID, ...)
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import uvicorn  # noqa: E402

from app import reccobeats_client, spotify_client  # noqa: E402

upstream = os.environ["FAKE_UPSTREAM_URL"].rstrip("/")
spotify_client.TOKEN_URL = f"{upstream}/api/token"
spotify_client.API_BASE = f"{upstream}/v1"
reccobeats_client.BASE_URL = upstream

from app.main import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
