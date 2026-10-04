"""Choosing landmarks for a fix, and refusing a fix whose page has changed."""

import pytest

from agent import actions
from memory import replay, store
from memory.landmarks import Landmark, choose, missing, on_snapshot

# The order form with submit_button_moved on, as aria_snapshot prints it.
SNAPSHOT = """\
- heading "Acme Supply Co." [level=1]
- heading "Order Details" [level=2]
- paragraph: Red Widget (SKU-1002) - $14.00
- button "Submit Purchase Request"
- text: Delivery date (MM/DD/YYYY)
- textbox "Delivery date (MM/DD/YYYY)":
  - /placeholder: MM/DD/YYYY
"""

FILL = actions.Action(kind="fill", role="textbox", name="Delivery date (MM/DD/YYYY)",
                      value="10/15/2026", reason="done by a person")
CLICK = actions.Action(kind="click", role="button", name="Submit Purchase Request",
                       reason="done by a person")


def test_snapshot_lines_with_a_name_are_read():
    assert on_snapshot(SNAPSHOT) == {
        Landmark("heading", "Acme Supply Co."),
        Landmark("heading", "Order Details"),
        Landmark("button", "Submit Purchase Request"),
        Landmark("textbox", "Delivery date (MM/DD/YYYY)"),
    }


def test_escaped_quotes_in_a_name():
    assert on_snapshot('- button "Say \\"hi\\""') == {Landmark("button", 'Say "hi"')}


def test_choose_takes_headings_then_targets_without_repeats():
    assert choose(SNAPSHOT, [FILL, CLICK, CLICK]) == [
        Landmark("heading", "Acme Supply Co."),
        Landmark("heading", "Order Details"),
        Landmark("textbox", "Delivery date (MM/DD/YYYY)"),
        Landmark("button", "Submit Purchase Request"),
    ]


def test_a_target_that_appears_later_is_not_a_landmark():
    later = actions.Action(kind="click", role="button", name="Confirm", reason="")
    assert Landmark("button", "Confirm") not in choose(SNAPSHOT, [CLICK, later])


def yes(question):
    return True


def never_asked(question):
    raise AssertionError(f"should not have been asked: {question}")


@pytest.fixture
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(500)
        yield page
        browser.close()


ORDER_FORM = (
    "<h1>Acme Supply Co.</h1><h2>Order Details</h2>"
    '<button onclick="this.textContent=\'Sent\'">Submit Purchase Request</button>'
    '<label for="d">Delivery date ({fmt})</label><input id="d">'
)


def test_missing_is_exact(page):
    page.set_content(ORDER_FORM.format(fmt="MM/DD/YYYY"))
    present = Landmark("button", "Submit Purchase Request")
    partial = Landmark("button", "Submit")  # a substring is not a match
    assert missing(page, [present, partial]) == [partial]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")


def test_a_fix_on_an_unchanged_page_is_replayed(page, temp_db):
    page.set_content(ORDER_FORM.format(fmt="MM/DD/YYYY"))
    store.save_fix("http://x/order/SKU-1002", "goal", [FILL, CLICK], SNAPSHOT)
    fix = replay.find_fix("http://x/order/SKU-1002", "goal")
    result = replay.replay(page, fix, confirm=yes)
    assert result.ok and not result.stale


def test_a_stale_fix_touches_nothing(page, temp_db):
    # The site switched to DD/MM/YYYY after the fix was made. Typing the
    # remembered 10/15/2026 here would be wrong, so the fix must not start.
    page.set_content(ORDER_FORM.format(fmt="DD/MM/YYYY"))
    store.save_fix("http://x/order/SKU-1002", "goal", [FILL, CLICK], SNAPSHOT)
    fix = replay.find_fix("http://x/order/SKU-1002", "goal")
    result = replay.replay(page, fix, confirm=never_asked)

    assert not result.ok and result.stale
    assert result.outcomes == []
    assert "Delivery date (MM/DD/YYYY)" in result.problem
    assert page.get_by_role("button", name="Sent").count() == 0
