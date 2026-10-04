"""Which steps of a fix must never be replayed without a person.

Re-typing into a field costs nothing; the form has not gone anywhere yet.
Pressing the button that places an order might cost real money, and doing
it twice because a replay could not tell the difference is the failure that
makes people distrust agents. So a fix can carry the agent up to a risky
step, but not over it: replay stops there and asks.

A step is risky if it clicks a button whose name contains one of RISKY_WORDS,
or if the person who recorded the fix marked it so. A person can add caution
but not remove it: there is no way to mark a step safe.
"""

import re

from agent import actions

RISKY_WORDS = (
    "place", "submit", "purchase", "order", "buy", "pay", "checkout",
    "confirm", "send", "delete", "remove", "cancel",
)

# Whole words only: "Payment details" is not "pay", "Reorder list" is not "order".
_RISKY = re.compile(r"\b(" + "|".join(RISKY_WORDS) + r")\b", re.IGNORECASE)


def looks_risky(step: actions.Action) -> bool:
    """A click on a button with a risky word in its name."""
    return step.kind == actions.CLICK and step.role == "button" and bool(_RISKY.search(step.name))


def risky_steps(steps: list[actions.Action], marked: set[int] = frozenset()) -> list[int]:
    """Indexes of the risky steps: the ones that look it, plus any marked."""
    return sorted({i for i, step in enumerate(steps) if looks_risky(step)} | set(marked))
