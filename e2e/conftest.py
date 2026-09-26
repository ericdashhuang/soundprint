"""Fixtures: start the fake upstream, the real backend and the real frontend
once per session, and give every test its own fresh Chrome.

Run `pytest --headed` to watch the browser. Set E2E_SKIP_BUILD=1 to reuse an
existing `frontend/.next` build instead of rebuilding the frontend.
"""

import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest
from selenium import webdriver

from pages.landing import LandingPage

E2E_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = E2E_DIR.parent / "frontend"
SCREENSHOT_DIR = E2E_DIR / "screenshots"

FAKE_UPSTREAM_PORT = 9100
BACKEND_PORT = 8000
FRONTEND_PORT = 3000

STARTUP_TIMEOUT_SECONDS = 60


def pytest_addoption(parser):
    parser.addoption("--headed", action="store_true", help="Show the Chrome window.")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Remember each phase's result on the test item so fixtures can tell
    whether the test failed (used to take a screenshot on failure)."""
    outcome = yield
    setattr(item, f"rep_{call.when}", outcome.get_result())


@dataclass
class Servers:
    frontend_url: str
    db_path: Path


def _assert_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            pytest.exit(
                f"Port {port} is already in use. Stop whatever is using it "
                "(a dev server?) and run the tests again.",
                returncode=2,
            )


def _wait_for_http(url: str, name: str, log_path: Path) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    log_tail = log_path.read_text()[-2000:] if log_path.exists() else "(no log)"
    pytest.exit(f"{name} did not start at {url}.\n--- log tail ---\n{log_tail}", returncode=2)


def _start(name: str, cmd: list[str], cwd: Path, env: dict, log_dir: Path) -> subprocess.Popen:
    log_path = log_dir / f"{name}.log"
    log_file = open(log_path, "w")
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log_file, stderr=subprocess.STDOUT)


@pytest.fixture(scope="session")
def servers():
    for port in (FAKE_UPSTREAM_PORT, BACKEND_PORT, FRONTEND_PORT):
        _assert_port_free(port)

    tmp = Path(tempfile.mkdtemp(prefix="soundprint-e2e-"))
    db_path = tmp / "e2e.db"
    base_env = os.environ.copy()
    processes: list[subprocess.Popen] = []

    try:
        processes.append(
            _start(
                "fake_upstream",
                [sys.executable, "-m", "uvicorn", "fake_upstream:app",
                 "--port", str(FAKE_UPSTREAM_PORT), "--log-level", "warning"],
                E2E_DIR, base_env, tmp,
            )
        )
        _wait_for_http(f"http://127.0.0.1:{FAKE_UPSTREAM_PORT}/health", "Fake upstream", tmp / "fake_upstream.log")

        backend_env = {
            **base_env,
            "FAKE_UPSTREAM_URL": f"http://127.0.0.1:{FAKE_UPSTREAM_PORT}",
            "DATABASE_URL": f"sqlite:///{db_path}",
            "SPOTIFY_CLIENT_ID": "fake-client-id",
            "SPOTIFY_CLIENT_SECRET": "fake-client-secret",
            "WARM_UP_ON_STARTUP": "false",
            "CORS_ORIGINS": f"http://localhost:{FRONTEND_PORT}",
        }
        processes.append(
            _start("backend", [sys.executable, "run_backend.py", str(BACKEND_PORT)], E2E_DIR, backend_env, tmp)
        )
        _wait_for_http(f"http://127.0.0.1:{BACKEND_PORT}/api/health", "Backend", tmp / "backend.log")

        # NEXT_PUBLIC_* values are baked in at build time, so the frontend must
        # be (re)built to point at the test backend.
        frontend_env = {**base_env, "NEXT_PUBLIC_API_BASE_URL": f"http://localhost:{BACKEND_PORT}"}
        if not os.environ.get("E2E_SKIP_BUILD"):
            build_log = tmp / "frontend-build.log"
            with open(build_log, "w") as log_file:
                build = subprocess.run(
                    ["npm", "run", "build"], cwd=FRONTEND_DIR, env=frontend_env,
                    stdout=log_file, stderr=subprocess.STDOUT,
                )
            if build.returncode != 0:
                pytest.exit(f"Frontend build failed.\n{build_log.read_text()[-2000:]}", returncode=2)
        processes.append(
            _start("frontend", ["npm", "run", "start", "--", "--port", str(FRONTEND_PORT)],
                   FRONTEND_DIR, frontend_env, tmp)
        )
        _wait_for_http(f"http://localhost:{FRONTEND_PORT}", "Frontend", tmp / "frontend.log")

        yield Servers(frontend_url=f"http://localhost:{FRONTEND_PORT}", db_path=db_path)
    finally:
        for process in reversed(processes):
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest.fixture
def driver(request, servers):
    options = webdriver.ChromeOptions()
    if not request.config.getoption("--headed"):
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    browser = webdriver.Chrome(options=options)
    yield browser

    failed = getattr(request.node, "rep_call", None) and request.node.rep_call.failed
    if failed:
        SCREENSHOT_DIR.mkdir(exist_ok=True)
        browser.save_screenshot(str(SCREENSHOT_DIR / f"{request.node.name}.png"))
    browser.quit()


@pytest.fixture
def landing_page(driver, servers) -> LandingPage:
    page = LandingPage(driver)
    page.open(servers.frontend_url)
    return page


@pytest.fixture
def target_album(servers):
    """Returns a function giving the secret target album name of the newest
    round, read straight from the backend's database. The game picks its
    target at random, so tests look it up instead of guessing."""

    def lookup() -> str:
        with sqlite3.connect(servers.db_path) as connection:
            row = connection.execute(
                "SELECT target_album_name FROM gameround ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        assert row is not None, "No round has been started yet."
        return row[0]

    return lookup
