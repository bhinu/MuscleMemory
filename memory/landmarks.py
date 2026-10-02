"""Reference points that say whether a saved fix still fits the page.

A fix is chosen by page and goal, but the page may have changed again since
it was recorded. Replaying it then would act on a page the person never saw.
So each fix carries landmarks -- things that were on the page when the fix
was made and must still be there for the fix to be trusted:

  - every heading on the page, which says *which* page this is
  - every control a step touches that was already on the page, which says
    the fix's own targets have not been renamed, moved out, or removed

A step whose target was not on the page yet (it appeared after an earlier
step, say on the next page) cannot be checked up front. It is still checked
as replay reaches it: replay stops at the first step that fails.

All landmarks are checked before any step runs. One missing means the fix is
stale and nothing is touched.
"""

import json
import re
from dataclasses import dataclass

from playwright.sync_api import Page

from agent import actions

# One line of an aria snapshot:  - button "Place Order"
#                                - heading "Order Details" [level=2]
# The name is a JSON-style string, so escaped quotes inside it are allowed.
_SNAPSHOT_LINE = re.compile(r'^\s*- ([a-z]+) ("(?:[^"\\]|\\.)*")', re.MULTILINE)


@dataclass(frozen=True)
class Landmark:
    role: str
    name: str

    def __str__(self) -> str:
        return f"{self.role} {self.name!r}"


def on_snapshot(snapshot: str) -> set[Landmark]:
    """Every named element in an aria snapshot."""
    return {
        Landmark(role, json.loads(quoted_name))
        for role, quoted_name in _SNAPSHOT_LINE.findall(snapshot)
    }


def choose(snapshot: str, steps: list[actions.Action]) -> list[Landmark]:
    """Pick the landmarks for a fix recorded on this snapshot.

    Ordered headings first, then step targets in step order, with no
    repeats, so a person reading them sees the page before the controls.
    """
    present = on_snapshot(snapshot)
    headings = sorted((m for m in present if m.role == "heading"), key=lambda m: m.name)
    targets = [Landmark(step.role, step.name) for step in steps]
    chosen = [m for m in headings + targets if m in present]
    return list(dict.fromkeys(chosen))


def missing(page: Page, landmarks: list[Landmark]) -> list[Landmark]:
    """The landmarks not on the page right now.

    Matched exactly, the same way browser.execute finds a target, so a
    landmark counts as present only if a step aimed at it would land.
    """
    return [
        m for m in landmarks
        if page.get_by_role(m.role, name=m.name, exact=True).count() == 0
    ]
