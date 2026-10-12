"""Fixtures shared by tests that need a browser or the real portal."""

import json
import threading
import time

import pytest


@pytest.fixture
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def portal(tmp_path, monkeypatch):
    """The real portal on a free port, with its own orders.db and chaos.json.

    Yields (base_url, set_mutations).
    """
    uvicorn = pytest.importorskip("uvicorn")
    from portal import chaos, db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "orders.db")
    monkeypatch.setattr(chaos, "CONFIG_PATH", tmp_path / "chaos.json")
    db.init_db()
    from portal.app import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    def set_mutations(*names):
        (tmp_path / "chaos.json").write_text(json.dumps({"active": list(names)}))

    yield f"http://127.0.0.1:{port}", set_mutations
    server.should_exit = True
    thread.join()
