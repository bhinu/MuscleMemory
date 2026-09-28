"""Everything that touches the live page: what the agent sees, and how it acts.

This is the only module that holds a Playwright Page. Keeping it separate is
what lets the decision-making be tested without a browser, and the browser be
tested without a model.
"""

from playwright.sync_api import Page

from agent.actions import CLICK, FILL, Action


def snapshot(page: Page) -> str:
    """The page as its accessibility tree: roles, names, and nothing else."""
    return page.locator("body").aria_snapshot()


def execute(page: Page, action: Action) -> str:
    """Carry out one action and return a short line describing what happened.

    exact=True matters: Playwright matches accessible names as substrings by
    default, which would let "Submit" quietly select "Submit Purchase Request".
    """
    target = page.get_by_role(action.role, name=action.name, exact=True)
    if action.kind == CLICK:
        target.click()
        return f"clicked {action.role} {action.name!r}"
    if action.kind == FILL:
        target.fill(action.value)
        return f"filled {action.role} {action.name!r} with {action.value!r}"
    raise ValueError(f"{action.kind} is not something the browser can do")
