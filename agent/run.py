"""The agent loop: look at the page, ask for one action, do it, repeat.

When the model says stuck, a person gets the browser at the terminal. When
they type resume, the agent carries on from wherever they left the page.

Start the portal first:
    uvicorn portal.app:app

Then:
    python -m agent.run                 # headless
    HEADED=1 python -m agent.run        # watch it drive
"""

import os
import sys

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from agent import actions, brain, browser, human

BASE_URL = os.environ.get("PORTAL_URL", "http://127.0.0.1:8000")
MAX_STEPS = 12
GOAL = (
    "Sign in with username 'buyer' and password 'hunter2'. Then order the "
    "product with SKU-1002 (Red Widget) for delivery on 10/15/2026, and "
    "confirm the order was placed."
)


def run(page, goal: str) -> str:
    """Drive the page until the model says done or stuck, or we run out of steps."""
    history: list[str] = []
    for step in range(1, MAX_STEPS + 1):
        action = brain.decide(goal, browser.snapshot(page), history)
        print(f"[{step}] {action.kind} -- {action.reason}")

        if action.kind == actions.DONE:
            return "DONE"
        if action.kind == actions.STUCK:
            takeover = human.take_over(page, action.reason)
            history.extend(takeover.outcomes)
            if takeover.aborted:
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
        page = browser_instance.new_page()
        page.set_default_timeout(5000)
        page.goto(f"{BASE_URL}/login")
        try:
            result = run(page, GOAL)
        finally:
            browser_instance.close()
    print(f"\n{result}")
    return 0 if result == "DONE" else 1


if __name__ == "__main__":
    sys.exit(main())
