"""The agent loop: look at the page, ask for one action, do it, repeat.

When the model says stuck, memory is checked first: a fix saved earlier for
the same page and goal is replayed (memory/replay.py). If there is none, or
it fails, a person gets the browser at the terminal. When they type resume,
what they did is saved as a fix (memory/store.py) and the agent carries on
from wherever they left it.

The model saying done does not end the story. The orders table is read before
and after the run, and the run only counts as a success if exactly the order
the goal asked for appeared in between (agent/verify.py).

A click that could place an order is treated differently from every other
action: the model gets one per run, and what it did is checked against the
orders table straight away (agent/safety.py). If that cannot be established,
the run halts rather than letting anything press the button again.

Start the portal first:
    uvicorn portal.app:app

Then:
    python -m agent.run                 # headless
    HEADED=1 python -m agent.run        # watch it drive
"""

import os
import sys
from datetime import date

from dotenv import load_dotenv
from collections.abc import Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from agent import actions, brain, browser, human, safety, verify
from agent.goal import Goal
from memory import replay, store

BASE_URL = os.environ.get("PORTAL_URL", "http://127.0.0.1:8000")
MAX_STEPS = 12
GOAL = Goal(sku="SKU-1002", product_name="Red Widget", delivery_date=date(2026, 10, 15))


def unstick(
    page,
    goal: str,
    why: str,
    snapshot: str,
    history: list[str],
    tried: set[int],
    budget: safety.Budget,
) -> bool:
    """Get past a stuck point: a saved fix if one fits, otherwise a person.

    Returns False if the person aborted. tried holds fixes already replayed
    this run; one that did not get the agent moving the first time is not
    replayed again, or a bad fix would loop until MAX_STEPS.

    A risky step taken here, by the fix or by the person, uses up budget:
    they may finish a submission, and the model may not submit after them.
    """
    # Read before anything touches the page: a fix belongs to the page as
    # the agent found it, not wherever replay or a person leaves it.
    stuck_url = page.url

    fix = replay.find_fix(stuck_url, goal, skip=tried)
    if fix is not None:
        tried.add(fix.id)
        print(f"     trying fix #{fix.id} from memory")
        result = replay.replay(
            page, fix, confirm=human.confirm, report=lambda line: print(f"     {line}")
        )
        history.extend(result.outcomes)
        # replay records one outcome per step it carried out, in order, so
        # the steps it took are the first len(outcomes) of the fix.
        for index in fix.risky:
            if index < len(result.outcomes):
                budget.spend(f"fix #{fix.id}", fix.steps[index])
        if result.ok:
            return True
        print(f"     {result.problem}")
        why = f"{why} (and {result.problem})"

    takeover = human.take_over(page, why)
    history.extend(takeover.outcomes)
    for index, step in enumerate(takeover.steps):
        if safety.is_consequential(step) or index in takeover.marked_risky:
            budget.spend("a person", step)
    if takeover.aborted:
        return False
    if takeover.steps:
        fix_id = store.save_fix(
            stuck_url, goal, takeover.steps, snapshot, takeover.marked_risky
        )
        print(f"     saved fix #{fix_id} for {store.page_key(stuck_url)}")
    return True


def consequential_click(
    page,
    action: actions.Action,
    budget: safety.Budget,
    read_orders: Callable[[], verify.Reading],
    history: list[str],
) -> safety.Outcome:
    """Make the model's one consequential click, and find out what it did.

    The caller halts on unknown. On not_there and nothing_placed it goes to
    a saved fix or a person. Nothing in this function hands a click that
    was made back to the model.
    """
    target = f"{action.role} {action.name!r}"
    if budget.spent:
        return safety.Outcome(
            safety.UNKNOWN,
            f"the model tried to click {target}, but {budget.spent_on} earlier in "
            f"this run, and a second such click could place a second order",
        )
    if not browser.present(page, action):
        # Checked before the click is spent: a button that is not there was
        # never pressed, so this is a wrong name, not an uncertain order.
        outcome = f"FAILED: no {target} on this page"
        print(f"     {outcome}")
        history.append(outcome)
        return safety.Outcome(safety.NOT_THERE, f"there is no {target} on this page")
    before = read_orders()
    if before.problem:
        # Not clicked at all: a click whose result could not be checked
        # afterwards is not worth making.
        return safety.Outcome(
            safety.UNKNOWN,
            f"did not click {target}: could not read the orders table first: {before.problem}",
        )

    budget.spend("the model", action)
    try:
        outcome = browser.execute(page, action)
        timed_out = False
    except PlaywrightTimeoutError:
        outcome = f"FAILED: clicking {target} timed out"
        timed_out = True
    verdict = safety.judge(before, verify.Reading() if timed_out else read_orders(), timed_out)
    outcome = f"{outcome} -- {verdict.reason}"
    print(f"     {outcome}")
    history.append(outcome)
    return verdict


def run(page, goal: str, read_orders: Callable[[], verify.Reading]) -> str:
    """Drive the page until the model says done or stuck, or we run out of steps.

    read_orders looks at the orders table right now. It is passed in rather
    than built here so the loop can be tested without a portal.
    """
    history: list[str] = []
    tried: set[int] = set()
    budget = safety.Budget()
    for step in range(1, MAX_STEPS + 1):
        snapshot = browser.snapshot(page)
        action = brain.decide(goal, snapshot, history)
        print(f"[{step}] {action.kind} -- {action.reason}")

        if action.kind == actions.DONE:
            return "DONE"
        if action.kind == actions.STUCK:
            if not unstick(page, goal, action.reason, snapshot, history, tried, budget):
                return f"STUCK: {action.reason}"
            continue

        if safety.is_consequential(action):
            verdict = consequential_click(page, action, budget, read_orders, history)
            if verdict.status == safety.UNKNOWN:
                return f"HALTED: {verdict.reason}"
            if verdict.status == safety.NOT_THERE:
                # The page is as the model saw it, so the snapshot from the
                # top of this step is still the right one to save a fix with.
                if not unstick(page, goal, verdict.reason, snapshot, history, tried, budget):
                    return f"STUCK: {verdict.reason}"
            if verdict.status == safety.NOTHING_PLACED:
                # Nothing is at stake yet, so this is an ordinary stuck
                # point on the page the click led to -- but not one the
                # model gets to click its way out of.
                why = f"clicked {action.role} {action.name!r} and no order was placed"
                if not unstick(page, goal, why, browser.snapshot(page), history, tried, budget):
                    return f"STUCK: {why}"
            continue

        try:
            outcome = browser.execute(page, action)
        except PlaywrightTimeoutError:
            outcome = f"FAILED: no {action.role} named {action.name!r} on this page"
        print(f"     {outcome}")
        history.append(outcome)

    return f"GAVE UP after {MAX_STEPS} steps"


def main() -> int:
    load_dotenv()
    with sync_playwright() as p:
        browser_instance = p.chromium.launch(headless=not os.environ.get("HEADED"))
        try:
            before = verify.read_orders(browser_instance, BASE_URL)
            page = browser_instance.new_page()
            page.set_default_timeout(5000)
            page.goto(f"{BASE_URL}/login")
            result = run(
                page, GOAL.sentence(), lambda: verify.read_orders(browser_instance, BASE_URL)
            )
            # Checked however the run ended: a run that got stuck or gave up
            # may still have placed an order on the way.
            after = verify.read_orders(browser_instance, BASE_URL)
        finally:
            browser_instance.close()
    verdict = verify.check(before, after, GOAL)
    print(f"\n{result}\norders: {verdict}")
    if result.startswith("HALTED"):
        print("A person needs to look at the portal before this run is retried.")
    return 0 if result == "DONE" and verdict.status == verify.VERIFIED else 1


if __name__ == "__main__":
    sys.exit(main())
