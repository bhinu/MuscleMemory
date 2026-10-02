"""Choosing a saved fix and replaying it."""

import pytest

from agent import actions
from memory import replay, store

URL = "http://127.0.0.1:8000/order/SKU-1002"
FILL = actions.Action(kind="fill", role="textbox", name="Delivery date",
                      value="10/15/2026", reason="done by a person")
CLICK = actions.Action(kind="click", role="button", name="Submit Purchase Request",
                       reason="done by a person")


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")


def test_no_fix_saved_means_none():
    assert replay.find_fix(URL, "goal") is None


def test_a_fix_for_another_goal_is_not_used():
    store.save_fix(URL, "order for 10/15/2026", [FILL], "")
    assert replay.find_fix(URL, "order for 11/01/2026") is None


def test_newest_matching_fix_wins_and_skip_falls_back():
    older = store.save_fix(URL, "goal", [FILL], "")
    newer = store.save_fix(URL, "goal", [FILL, CLICK], "")
    assert replay.find_fix(URL, "goal").id == newer
    assert replay.find_fix(URL, "goal", skip={newer}).id == older
    assert replay.find_fix(URL, "goal", skip={newer, older}) is None


@pytest.fixture
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(500)
        yield page
        browser.close()


def test_replay_runs_every_step(page):
    page.set_content(
        '<label for="d">Delivery date</label><input id="d">'
        '<button onclick="this.textContent=\'Sent\'">Submit Purchase Request</button>'
    )
    fix_id = store.save_fix(URL, "goal", [FILL, CLICK], "")
    result = replay.replay(page, replay.find_fix(URL, "goal"))

    assert result.ok
    assert len(result.outcomes) == 2
    assert page.get_by_role("textbox").input_value() == "10/15/2026"
    assert page.get_by_role("button", name="Sent").count() == 1
    assert f"fix #{fix_id}" in result.outcomes[0]


def test_replay_stops_at_the_first_step_that_fails(page):
    # The date field was renamed, so step 1 fails -- and step 2, the click,
    # must not happen with the date left empty.
    page.set_content(
        '<label for="d">Required delivery date</label><input id="d">'
        '<button onclick="this.textContent=\'Sent\'">Submit Purchase Request</button>'
    )
    store.save_fix(URL, "goal", [FILL, CLICK], "")
    result = replay.replay(page, replay.find_fix(URL, "goal"))

    assert not result.ok
    assert result.outcomes == []
    assert "step 1" in result.problem
    assert page.get_by_role("button", name="Sent").count() == 0
