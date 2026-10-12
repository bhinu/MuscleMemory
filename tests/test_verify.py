"""Checking a run against the orders table."""

import json
import socket
import threading
import time
import urllib.parse
import urllib.request
from datetime import date

import pytest

from agent import verify
from agent.goal import Goal
from agent.verify import Order, Reading

GOAL = Goal(sku="SKU-1002", product_name="Red Widget", delivery_date=date(2026, 10, 15))
RIGHT = Order("ORD-00002", "SKU-1002", "2026-10-15")
OLD = Order("ORD-00001", "SKU-1002", "2026-10-15")  # there before the run started


# --- the goal ---------------------------------------------------------------


def test_the_sentence_is_word_for_word_the_one_fixes_were_saved_under():
    assert GOAL.sentence() == (
        "Sign in with username 'buyer' and password 'hunter2'. Then order the "
        "product with SKU-1002 (Red Widget) for delivery on 10/15/2026, and "
        "confirm the order was placed."
    )


def test_the_expected_date_is_the_same_day_the_sentence_asks_for():
    goal = Goal(sku="SKU-1001", product_name="Blue Widget", delivery_date=date(2026, 3, 4))
    assert "03/04/2026" in goal.sentence()
    assert goal.expected_date() == "2026-03-04"


# --- check: no browser needed -----------------------------------------------


def test_one_new_order_matching_the_goal_is_verified():
    result = verify.check(Reading([OLD]), Reading([RIGHT, OLD]), GOAL)
    assert result.status == verify.VERIFIED
    assert result.detail == "ORD-00002"
    assert result.new_order_count == 1


def test_no_new_order_is_missing_even_if_an_old_one_matches():
    assert verify.check(Reading([OLD]), Reading([OLD]), GOAL).status == verify.MISSING
    assert verify.check(Reading(), Reading(), GOAL).status == verify.MISSING
    assert verify.check(Reading([OLD]), Reading([OLD]), GOAL).new_order_count == 0


def test_day_and_month_swapped_is_wrong_details():
    # What date_format_dmy does to an ambiguous date typed as MM/DD.
    goal = Goal(sku="SKU-1002", product_name="Red Widget", delivery_date=date(2026, 3, 4))
    swapped = Order("ORD-00002", "SKU-1002", "2026-04-03")
    result = verify.check(Reading(), Reading([swapped]), goal)
    assert result.status == verify.WRONG_DETAILS
    assert "delivery date 2026-04-03, expected 2026-03-04" in result.detail


def test_the_wrong_product_is_wrong_details():
    result = verify.check(Reading(), Reading([Order("ORD-00002", "SKU-1001", "2026-10-15")]), GOAL)
    assert result.status == verify.WRONG_DETAILS
    assert "SKU SKU-1001, expected SKU-1002" in result.detail


def test_the_right_order_twice_is_duplicate():
    again = Order("ORD-00003", "SKU-1002", "2026-10-15")
    result = verify.check(Reading([OLD]), Reading([again, RIGHT, OLD]), GOAL)
    assert result.status == verify.DUPLICATE
    assert "2 times" in result.detail
    assert result.new_order_count == 2


def test_a_wrong_order_beside_a_right_one_is_wrong_details_not_duplicate():
    wrong = Order("ORD-00003", "SKU-1002", "2026-10-16")
    result = verify.check(Reading(), Reading([wrong, RIGHT]), GOAL)
    assert result.status == verify.WRONG_DETAILS
    assert "ORD-00003" in result.detail and "ORD-00002" not in result.detail


def test_a_double_submit_is_still_counted_when_the_details_are_wrong():
    # Mixed case: the status says wrong_details, the count says two orders.
    wrong = Order("ORD-00003", "SKU-1002", "2026-10-16")
    result = verify.check(Reading([OLD]), Reading([wrong, RIGHT, OLD]), GOAL)
    assert result.status == verify.WRONG_DETAILS
    assert result.new_order_count == 2


def test_an_unreadable_table_is_unverifiable_with_the_reason():
    broken = Reading(problem="portal is down")
    before = verify.check(broken, Reading([RIGHT]), GOAL)
    after = verify.check(Reading(), broken, GOAL)
    assert before.status == after.status == verify.UNVERIFIABLE
    assert "before the run: portal is down" in before.detail
    assert "after the run: portal is down" in after.detail
    assert before.new_order_count is None and after.new_order_count is None


def test_a_verification_prints_as_status_and_detail():
    assert str(verify.Verification(verify.MISSING, "no new order")) == "missing: no new order"
    assert str(verify.Verification(verify.VERIFIED)) == "verified"


# --- parse_orders: a browser, but no portal ---------------------------------


@pytest.fixture
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page()
    page.set_default_timeout(500)
    return page


ORDERS_PAGE = """<h1>Acme Supply Co.</h1><h2>All Orders</h2>{body}"""
TABLE = """<table>
  <tr><th>Order</th><th>Product</th><th>SKU</th><th>Delivery date</th><th>Placed at (UTC)</th></tr>
  <tr><td>ORD-00002</td><td>Red Widget</td><td>SKU-1002</td><td>2026-10-15</td><td>t2</td></tr>
  <tr><td>ORD-00001</td><td>Blue Widget</td><td>SKU-1001</td><td>2026-11-01</td><td>t1</td></tr>
</table>"""


def test_parse_reads_every_row(page):
    page.set_content(ORDERS_PAGE.format(body=TABLE))
    assert verify.parse_orders(page) == Reading(
        [RIGHT, Order("ORD-00001", "SKU-1001", "2026-11-01")]
    )


def test_parse_finds_columns_by_header_not_position(page):
    reordered = """<table>
      <tr><th>Delivery date</th><th>SKU</th><th>Order</th></tr>
      <tr><td>2026-10-15</td><td>SKU-1002</td><td>ORD-00002</td></tr>
    </table>"""
    page.set_content(ORDERS_PAGE.format(body=reordered))
    assert verify.parse_orders(page) == Reading([RIGHT])


def test_parse_no_orders_yet_is_an_empty_reading_not_a_problem(page):
    page.set_content(ORDERS_PAGE.format(body="<p>No orders yet.</p>"))
    assert verify.parse_orders(page) == Reading()


def test_parse_reports_a_page_that_is_not_the_orders_page(page):
    page.set_content("<h1>Acme Supply Co.</h1><h2>Sign In</h2>")
    assert "is not the orders page" in verify.parse_orders(page).problem


def test_parse_reports_a_renamed_column(page):
    page.set_content(ORDERS_PAGE.format(body=TABLE.replace("Delivery date", "Arrives")))
    assert "no column named Delivery date" in verify.parse_orders(page).problem


def test_read_orders_with_no_portal_reports_instead_of_raising(browser):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # free, and nothing is listening on it
    reading = verify.read_orders(browser, f"http://127.0.0.1:{port}")
    assert reading.orders == [] and reading.problem


# --- read_orders against the real portal -------------------------------------


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


def place_order(base_url, sku, typed_date):
    """Submit the order form directly, the way a browser would."""
    request = urllib.request.Request(
        f"{base_url}/order",
        data=urllib.parse.urlencode({"sku": sku, "delivery_date": typed_date}).encode(),
        headers={"Cookie": "session=buyer"},
    )
    urllib.request.urlopen(request).close()


def test_a_correct_order_on_the_real_portal_is_verified(browser, portal):
    base_url, _ = portal
    place_order(base_url, "SKU-1001", "11/01/2026")  # someone else's, earlier
    before = verify.read_orders(browser, base_url)
    place_order(base_url, "SKU-1002", "10/15/2026")
    after = verify.read_orders(browser, base_url)
    assert before.problem == "" and len(before.orders) == 1
    assert verify.check(before, after, GOAL).status == verify.VERIFIED


def test_the_dmy_mutation_is_caught_on_the_real_portal(browser, portal):
    base_url, set_mutations = portal
    set_mutations("date_format_dmy")
    goal = Goal(sku="SKU-1002", product_name="Red Widget", delivery_date=date(2026, 3, 4))
    before = verify.read_orders(browser, base_url)
    place_order(base_url, goal.sku, "03/04/2026")  # MM/DD, as the goal sentence writes it
    after = verify.read_orders(browser, base_url)
    result = verify.check(before, after, goal)
    assert result.status == verify.WRONG_DETAILS
    assert "delivery date 2026-04-03, expected 2026-03-04" in result.detail
