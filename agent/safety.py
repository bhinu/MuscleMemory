"""The model gets one consequential click per run, and its result is checked.

Filling a field or following a link can be repeated for free. Pressing the
button that places an order cannot: a second press is a second order. So a
click like that is not handed back to the model to try again. It is made at
most once, and the orders table is read on either side of it to see what it
actually did:

  confirmed      -- exactly one new order. Carry on.
  not_there      -- the button the model named is not on the page, so no
                    click was made and the model's one click is not used up.
                    An ordinary stuck point: a saved fix or a person can
                    find the button that is there.
  nothing_placed -- the click went through and no order appeared (a rejected
                    date, a new confirm step). Nothing is at stake yet, so a
                    person can finish the job; the model still may not press
                    such a button again.
  unknown        -- the button was there and the click timed out, more than
                    one order appeared, or the table could not be read.
                    Nobody knows what state the portal is in, so the run
                    halts without touching it again.

Which clicks count is decided by memory/risk.py, so "risky" means one thing
whether the model is clicking or a saved fix is being replayed.
"""

from dataclasses import dataclass

from agent import actions
from agent.verify import Reading
from memory.risk import looks_risky

CONFIRMED = "confirmed"
NOT_THERE = "not_there"
NOTHING_PLACED = "nothing_placed"
UNKNOWN = "unknown"


def is_consequential(action: actions.Action) -> bool:
    """Could this action place an order or do something that cannot be undone?

    This is keyword matching on the button's name (see memory/risk.py), so
    it will not recognise a confirm button labelled "Yes" or "Continue".
    That case is covered from the other side: the first, recognised click
    places no order, which hands the page to a person (nothing_placed)
    rather than leaving the model to press whatever comes next.
    """
    return looks_risky(action)


@dataclass
class Budget:
    """Whether this run's one consequential click has been used, and by what.

    Clicks made by a replayed fix or by a person use it up too: they are
    allowed to complete a submission, but the model must not submit again
    after them.
    """

    spent_on: str = ""

    @property
    def spent(self) -> bool:
        return bool(self.spent_on)

    def spend(self, who: str, action: actions.Action) -> None:
        # The first click is the one worth naming when a second is refused.
        if not self.spent:
            self.spent_on = f"{who} clicked {action.role} {action.name!r}"


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str = ""


def judge(before: Reading, after: Reading, timed_out: bool) -> Outcome:
    """What a consequential click did, going by the orders table around it."""
    if timed_out:
        return Outcome(UNKNOWN, "the click timed out, so it may or may not have gone through")
    if after.problem:
        return Outcome(UNKNOWN, f"could not read the orders table after the click: {after.problem}")
    already_there = {order.number for order in before.orders}
    new = sorted(order.number for order in after.orders if order.number not in already_there)
    if not new:
        return Outcome(NOTHING_PLACED, "no order was placed")
    if len(new) > 1:
        return Outcome(UNKNOWN, f"one click, but {len(new)} new orders: {', '.join(new)}")
    return Outcome(CONFIRMED, f"order {new[0]} was placed")
