"""Risky steps are never replayed without a person saying yes."""

import pytest

from agent import actions, human
from memory import replay, store
from memory.risk import looks_risky, risky_steps


def click(role, name):
    return actions.Action(kind="click", role=role, name=name, reason="done by a person")


FILL = actions.Action(kind="fill", role="textbox", name="Delivery date",
                      value="10/15/2026", reason="done by a person")
SUBMIT = click("button", "Submit Purchase Request")


@pytest.mark.parametrize(
    "step",
    [
        click("button", "Place Order"),
        click("button", "Submit Purchase Request"),
        click("button", "PAY NOW"),
        click("button", "Confirm"),
        click("button", "Delete account"),
    ],
)
def test_risky(step):
    assert looks_risky(step)


@pytest.mark.parametrize(
    "step",
    [
        click("button", "Sign In"),
        click("button", "Payment details"),  # "pay" only as a whole word
        click("button", "Reorder list"),  # likewise "order"
        click("link", "Order"),  # opens the order form; buttons only
        actions.Action(kind="fill", role="textbox", name="Order notes",
                       value="x", reason=""),  # typing places nothing
    ],
)
def test_not_risky(step):
    assert not looks_risky(step)


def test_marked_steps_join_the_ones_that_look_risky():
    steps = [FILL, click("button", "Next"), SUBMIT]
    assert risky_steps(steps) == [2]
    assert risky_steps(steps, marked={1}) == [1, 2]


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")


def test_risky_steps_are_saved_with_the_fix():
    store.save_fix("http://x/order/SKU-1", "goal", [FILL, click("button", "Next"), SUBMIT],
                   "", marked_risky={1})
    [fix] = store.fixes_for("http://x/order/SKU-1")
    assert fix.risky == [1, 2]


@pytest.fixture
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(500)
        page.set_content(
            '<label for="d">Delivery date</label><input id="d">'
            '<button onclick="this.textContent=\'Sent\'">Submit Purchase Request</button>'
        )
        yield page
        browser.close()


def answering(answer):
    """A stand-in person who answers every question the same way."""
    asked = []

    def confirm(question):
        asked.append(question)
        return answer

    confirm.asked = asked
    return confirm


def test_replay_carries_up_to_a_risky_step_and_stops_there(page):
    store.save_fix("http://x/order/SKU-1", "goal", [FILL, SUBMIT], "")
    no = answering(False)
    result = replay.replay(page, replay.find_fix("http://x/order/SKU-1", "goal"), confirm=no)

    assert not result.ok and result.held
    assert page.get_by_role("textbox").input_value() == "10/15/2026"  # safe step ran
    assert page.get_by_role("button", name="Sent").count() == 0  # risky one did not
    assert len(no.asked) == 1 and "Submit Purchase Request" in no.asked[0]


def test_a_yes_lets_the_risky_step_through(page):
    store.save_fix("http://x/order/SKU-1", "goal", [FILL, SUBMIT], "")
    yes = answering(True)
    result = replay.replay(page, replay.find_fix("http://x/order/SKU-1", "goal"), confirm=yes)

    assert result.ok
    assert page.get_by_role("button", name="Sent").count() == 1
    assert len(yes.asked) == 1  # asked about the click only, not the fill
    assert result.outcomes[1].endswith("(approved by a person)")


def test_replay_will_not_run_without_a_way_to_ask(page):
    store.save_fix("http://x/order/SKU-1", "goal", [FILL, SUBMIT], "")
    with pytest.raises(TypeError):
        replay.replay(page, replay.find_fix("http://x/order/SKU-1", "goal"))


@pytest.mark.parametrize("typed, answer", [("y", True), ("YES", True), ("", False),
                                           ("n", False), ("sure", False)])
def test_confirm_needs_an_explicit_yes(typed, answer):
    assert human.confirm("Take this step?", read=lambda _: typed) is answer


def test_confirm_with_no_terminal_is_no():
    def no_terminal(_):
        raise EOFError

    assert human.confirm("Take this step?", read=no_terminal) is False


def test_a_person_can_mark_their_last_step_risky(page):
    lines = iter(["risky",  # nothing to mark yet: ignored
                  'fill textbox "Delivery date" 10/15/2026', "risky", "resume"])
    result = human.take_over(page, "stuck", read=lambda _: next(lines))
    assert result.marked_risky == {0}
