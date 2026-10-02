"""Use a saved fix instead of calling a person.

When the agent is stuck, it asks here first. A fix is only a candidate if it
was saved for the same page *and* the same goal: a fix's steps carry values
from the goal they were recorded under (a delivery date, a quantity), so
replaying them for a different goal would type the wrong thing confidently.

Replay stops at the first step that does not work. Whatever happened up to
that point is reported, and the caller hands the page to a person.
"""

from dataclasses import dataclass, field

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from agent import browser
from memory import store


@dataclass
class Replay:
    """How a replay went."""

    ok: bool
    outcomes: list[str] = field(default_factory=list)
    problem: str = ""


def find_fix(url: str, goal: str, skip: set[int] = frozenset()) -> store.Fix | None:
    """The newest fix for this page and goal, leaving out ids in skip."""
    for fix in store.fixes_for(url):
        if fix.goal == goal and fix.id not in skip:
            return fix
    return None


def replay(page: Page, fix: store.Fix) -> Replay:
    """Carry out a fix's steps in order, stopping at the first that fails."""
    result = Replay(ok=True)
    for number, step in enumerate(fix.steps, start=1):
        try:
            outcome = browser.execute(page, step)
        except PlaywrightTimeoutError:
            result.ok = False
            result.problem = (
                f"step {number} of fix #{fix.id} failed: "
                f"no {step.role} named {step.name!r} on this page"
            )
            return result
        result.outcomes.append(f"memory (fix #{fix.id}) {outcome}")
    return result
