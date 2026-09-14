import os

os.environ.setdefault("SPOTIFY_CLIENT_ID", "test-client-id")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# The app's startup warm-up (app/warmup.py) makes real outbound HTTP calls to
# Spotify/ReccoBeats - never do that in the test suite (see project AGENTS.md).
os.environ.setdefault("WARM_UP_ON_STARTUP", "false")

import pytest
from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


@pytest.fixture()
def client():
    init_db()
    with TestClient(app) as test_client:
        yield test_client
