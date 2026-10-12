"""The model's one consequential click per run."""

import pytest

from agent import actions, human, run, safety
from agent.verify import Order, Reading
from memory import store

OLD = Order("ORD-00001", "SKU-1002", "2026-10-15")
NEW = Order("ORD-00002", "SKU-1002", "2026-10-15")
EXTRA = Order("ORD-00003", "SKU-1002", "2026-10-15")

PLACE = actions.Action(kind="click", role="button", name="Place Order")
FILL = actions.Action(kind="fill", role="textbox", name="Delivery date", value="10/15/2026")
DONE = actions.Action(kind="done")
STUCK = actions.Action(kind="stuck", reason="lost")


# --- judge: no browser needed -------------------------------------------------


def test_one_new_order_is_confirmed():
    outcome = safety.judge(Reading([OLD]), Reading([NEW, OLD]), timed_out=False)
    assert outcome == safety.Outcome(safety.CONFIRMED, "order ORD-00002 was placed")


def test_no_new_order_is_nothing_placed():
    assert safety.judge(Reading([OLD]), Reading([OLD]), timed_out=False).status == safety.NOTHING_PLACED


def test_more_than_one_new_order_is_unknown():
    outcome = safety.judge(Reading([OLD]), Reading([EXTRA, NEW, OLD]), timed_out=False)
    assert outcome.status == safety.UNKNOWN
    assert "2 new orders" in outcome.reason


def test_a_timeout_is_unknown_whatever_the_table_says():
    assert safety.judge(Reading([OLD]), Reading([OLD]), timed_out=True).status == safety.UNKNOWN


def test_an_unreadable_table_after_the_click_is_unknown():
    outcome = safety.judge(Reading([OLD]), Reading(problem="portal is down"), timed_out=False)
    assert outcome.status == safety.UNKNOWN
    assert "portal is down" in outcome.reason


def test_a_budget_remembers_the_first_click_that_spent_it():
    budget = safety.Budget()
    assert not budget.spent
    budget.spend("the model", PLACE)
    budget.spend("a person", PLACE)
    assert budget.spent and budget.spent_on == "the model clicked button 'Place Order'"


# --- the run loop: a browser, a scripted model, and a scripted orders table ---

# Each button counts its own presses, so a test can tell "refused" from
# "clicked and nothing happened".
FORM = """<h2>Order Details</h2>
<label for="d">Delivery date</label><input id="d">
<button type="button" onclick="window.placed = (window.placed || 0) + 1">Place Order</button>
<button type="button" onclick="window.yes = (window.yes || 0) + 1">Yes</button>"""


@pytest.fixture
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(500)
        page.set_content(FORM)
        yield page
        browser.close()


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")


def presses(page, counter):
    return page.evaluate(f"window.{counter} || 0")


def model(monkeypatch, *script):
    """Make the model return these actions in turn. Returns the list of
    actions it has been asked for so far, to check when it was *not* asked."""
    remaining, asked = list(script), []

    def decide(goal, snapshot, history):
        asked.append(remaining.pop(0))
        return asked[-1]

    monkeypatch.setattr(run.brain, "decide", decide)
    return asked


def orders(*readings):
    """An orders table that shows these readings, one per look."""
    remaining = list(readings)
    return lambda: remaining.pop(0)


def person(monkeypatch, *lines):
    """Put a person at the terminal who types these lines when taken over to."""
    typed = iter(lines)
    real = human.take_over
    monkeypatch.setattr(
        run.human, "take_over", lambda page, why: real(page, why, read=lambda prompt: next(typed))
    )


def nobody(monkeypatch):
    def take_over(page, why):
        raise AssertionError(f"a person should not have been called: {why}")

    monkeypatch.setattr(run.human, "take_over", take_over)


def test_a_confirmed_click_lets_the_run_finish(page, monkeypatch):
    model(monkeypatch, FILL, PLACE, DONE)
    nobody(monkeypatch)
    assert run.run(page, "goal", orders(Reading([OLD]), Reading([NEW, OLD]))) == "DONE"
    assert presses(page, "placed") == 1


def test_a_click_that_times_out_halts_and_is_not_offered_to_the_model_again(page, monkeypatch):
    missing = actions.Action(kind="click", role="button", name="Submit Purchase Request")
    asked = model(monkeypatch, missing, missing, DONE)
    nobody(monkeypatch)
    result = run.run(page, "goal", orders(Reading([OLD])))
    assert result.startswith("HALTED: the click timed out")
    assert asked == [missing]


def test_two_orders_from_one_click_halts(page, monkeypatch):
    model(monkeypatch, PLACE, DONE)
    nobody(monkeypatch)
    result = run.run(page, "goal", orders(Reading([OLD]), Reading([EXTRA, NEW, OLD])))
    assert result.startswith("HALTED: one click, but 2 new orders")


def test_an_unreadable_table_beforehand_halts_without_clicking(page, monkeypatch):
    model(monkeypatch, PLACE, DONE)
    nobody(monkeypatch)
    result = run.run(page, "goal", orders(Reading(problem="portal is down")))
    assert result.startswith("HALTED: did not click button 'Place Order'")
    assert presses(page, "placed") == 0


def test_an_unreadable_table_afterwards_halts(page, monkeypatch):
    model(monkeypatch, PLACE, DONE)
    nobody(monkeypatch)
    result = run.run(page, "goal", orders(Reading([OLD]), Reading(problem="portal is down")))
    assert result.startswith("HALTED: could not read the orders table after the click")


def test_a_confirm_step_goes_to_a_person_and_the_model_cannot_submit_again(page, monkeypatch):
    # The model presses Place Order and no order appears: the portal wants a
    # confirmation the model has never seen. A person presses "Yes" -- a
    # name no keyword list would catch. The model then tries Place Order
    # again and is stopped before the click.
    asked = model(monkeypatch, PLACE, PLACE, DONE)
    person(monkeypatch, 'click button "Yes"', "resume")
    result = run.run(page, "goal", orders(Reading([OLD]), Reading([OLD])))

    assert result.startswith("HALTED: the model tried to click button 'Place Order'")
    assert "the model clicked button 'Place Order' earlier" in result
    assert presses(page, "placed") == 1
    assert presses(page, "yes") == 1
    assert asked == [PLACE, PLACE]
    # What the person did was saved as a fix, as after any takeover.
    [fix] = store.fixes_for(page.url)
    assert [(s.kind, s.name) for s in fix.steps] == [("click", "Yes")]


def test_nothing_placed_and_the_person_aborts_is_stuck(page, monkeypatch):
    model(monkeypatch, PLACE, DONE)
    person(monkeypatch, "abort")
    result = run.run(page, "goal", orders(Reading([OLD]), Reading([OLD])))
    assert result == "STUCK: clicked button 'Place Order' and no order was placed"


def test_a_persons_submit_uses_up_the_models_click(page, monkeypatch):
    model(monkeypatch, STUCK, PLACE, DONE)
    person(monkeypatch, 'click button "Place Order"', "resume")
    result = run.run(page, "goal", orders())  # the table is never consulted
    assert result.startswith("HALTED: the model tried to click button 'Place Order'")
    assert "a person clicked button 'Place Order' earlier" in result
    assert presses(page, "placed") == 1


def test_a_step_a_person_marked_risky_uses_up_the_models_click(page, monkeypatch):
    model(monkeypatch, STUCK, PLACE, DONE)
    person(monkeypatch, 'click button "Yes"', "risky", "resume")
    result = run.run(page, "goal", orders())
    assert "a person clicked button 'Yes' earlier" in result
    assert presses(page, "placed") == 0


def test_a_replayed_submit_uses_up_the_models_click(page, monkeypatch):
    store.save_fix(page.url, "goal", [FILL, PLACE], "")
    model(monkeypatch, STUCK, PLACE, DONE)
    nobody(monkeypatch)
    monkeypatch.setattr(run.human, "confirm", lambda question: True)
    result = run.run(page, "goal", orders())
    assert result.startswith("HALTED: the model tried to click button 'Place Order'")
    assert "fix #1 clicked button 'Place Order' earlier" in result
    assert presses(page, "placed") == 1


def test_a_replay_that_stopped_before_its_risky_step_leaves_the_click_unspent(page, monkeypatch):
    store.save_fix(page.url, "goal", [FILL, PLACE], "")
    model(monkeypatch, STUCK, PLACE, DONE)
    person(monkeypatch, "resume")  # called because the replay was refused; does nothing
    monkeypatch.setattr(run.human, "confirm", lambda question: False)
    assert run.run(page, "goal", orders(Reading([OLD]), Reading([NEW, OLD]))) == "DONE"
    assert presses(page, "placed") == 1


def test_an_ordinary_failed_click_still_goes_back_to_the_model(page, monkeypatch):
    nowhere = actions.Action(kind="click", role="link", name="Back to products")
    asked = model(monkeypatch, nowhere, DONE)
    nobody(monkeypatch)
    assert run.run(page, "goal", orders()) == "DONE"
    assert asked == [nowhere, DONE]
