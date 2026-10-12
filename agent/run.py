"""The agent loop: look at the page, ask for one action, do it, repeat.

When the model says stuck, memory is checked first: a fix saved earlier for
the same page and goal is replayed (memory/replay.py). If there is none, or
it fails, a person gets the browser at the terminal. When they type resume,
what they did is saved as a fix (memory/store.py) and the agent carries on
from wherever they left it.

The model saying done does not end the story. The orders table is read before
and after the run, and the run only counts as a success if exactly the order
the goal asked for appeared in between (agent/verify.py).

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
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from agent import actions, brain, browser, human, verify
from agent.goal import Goal
from memory import replay, store

BASE_URL = os.environ.get("PORTAL_URL", "http://127.0.0.1:8000")
MAX_STEPS = 12
GOAL = Goal(sku="SKU-1002", product_name="Red Widget", delivery_date=date(2026, 10, 15))


def unstick(page, goal: str, why: str, snapshot: str, history: list[str], tried: set[int]) -> bool:
    """Get past a stuck point: a saved fix if one fits, otherwise a person.

    Returns False if the person aborted. tried holds fixes already replayed
    this run; one that did not get the agent moving the first time is not
    replayed again, or a bad fix would loop until MAX_STEPS.
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
        if result.ok:
            return True
        print(f"     {result.problem}")
        why = f"{why} (and {result.problem})"

    takeover = human.take_over(page, why)
    history.extend(takeover.outcomes)
    if takeover.aborted:
        return False
    if takeover.steps:
        fix_id = store.save_fix(
            stuck_url, goal, takeover.steps, snapshot, takeover.marked_risky
        )
        print(f"     saved fix #{fix_id} for {store.page_key(stuck_url)}")
    return True


def run(page, goal: str) -> str:
    """Drive the page until the model says done or stuck, or we run out of steps."""
    history: list[str] = []
    tried: set[int] = set()
    for step in range(1, MAX_STEPS + 1):
        snapshot = browser.snapshot(page)
        action = brain.decide(goal, snapshot, history)
        print(f"[{step}] {action.kind} -- {action.reason}")

        if action.kind == actions.DONE:
            return "DONE"
        if action.kind == actions.STUCK:
            if not unstick(page, goal, action.reason, snapshot, history, tried):
                return f"STUCK: {action.reason}"
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
            result = run(page, GOAL.sentence())
            # Checked however the run ended: a run that got stuck or gave up
            # may still have placed an order on the way.
            after = verify.read_orders(browser_instance, BASE_URL)
        finally:
            browser_instance.close()
    verdict = verify.check(before, after, GOAL)
    print(f"\n{result}\norders: {verdict}")
    return 0 if result == "DONE" and verdict.status == verify.VERIFIED else 1


if __name__ == "__main__":
    sys.exit(main())
