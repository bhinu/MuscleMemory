"""Check what a run actually did, instead of taking the model's word for it.

The model says done when the page in front of it looks like success. That is
not the same as the right order existing: with date_format_dmy on, typing
03/04/2026 gets a cheerful confirmation page for an order on the wrong day.

So the orders table is read once before the run and once after, and the
difference is compared with the goal. There are five answers:

  verified      -- exactly one new order, with the goal's SKU and date
  wrong_details -- a new order exists that is not what the goal asked for
  duplicate     -- the right order, placed more than once
  missing       -- no new order
  unverifiable  -- the orders table could not be read, so nothing is known

The table is read through the portal's /orders page, never from orders.db:
that file is the portal's own (see portal/db.py).
"""

from dataclasses import dataclass, field

from playwright.sync_api import Browser, Page
from playwright.sync_api import Error as PlaywrightError

from agent.goal import PASSWORD, USERNAME, Goal

VERIFIED = "verified"
WRONG_DETAILS = "wrong_details"
DUPLICATE = "duplicate"
MISSING = "missing"
UNVERIFIABLE = "unverifiable"

# The columns of the orders table this module depends on, by header text.
_NUMBER, _SKU, _DATE = "Order", "SKU", "Delivery date"


@dataclass(frozen=True)
class Order:
    """One row of the orders table: just the columns verification compares."""

    number: str
    sku: str
    delivery_date: str  # ISO, as the portal stores it


@dataclass(frozen=True)
class Reading:
    """One look at the orders table: the orders, or why it could not be read."""

    orders: list[Order] = field(default_factory=list)
    problem: str = ""


@dataclass(frozen=True)
class Verification:
    status: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.status}: {self.detail}" if self.detail else self.status


def parse_orders(page: Page) -> Reading:
    """Read the orders table off a page that is already showing /orders.

    Columns are found by their header text, not their position, so a
    reordered table is still read correctly and a renamed column is a
    problem reported rather than a wrong value compared.
    """
    if page.get_by_role("heading", name="All Orders", exact=True).count() == 0:
        return Reading(problem=f"{page.url} is not the orders page")
    rows = page.locator("table tr")
    if rows.count() == 0:
        if page.get_by_text("No orders yet.", exact=True).count() == 0:
            return Reading(problem="the orders page has neither a table nor 'No orders yet.'")
        return Reading()

    headers = [text.strip() for text in rows.first.locator("th").all_inner_texts()]
    absent = [name for name in (_NUMBER, _SKU, _DATE) if name not in headers]
    if absent:
        return Reading(problem=f"the orders table has no column named {', '.join(absent)}")
    number, sku, delivery = (headers.index(name) for name in (_NUMBER, _SKU, _DATE))

    orders = []
    for row in rows.all()[1:]:
        cells = [text.strip() for text in row.locator("td").all_inner_texts()]
        if len(cells) != len(headers):
            return Reading(problem=f"an orders table row has {len(cells)} cells, expected {len(headers)}")
        orders.append(Order(cells[number], cells[sku], cells[delivery]))
    return Reading(orders)


def read_orders(browser: Browser, base_url: str) -> Reading:
    """Sign in on the side and read the orders table. Never raises.

    A separate browser context has its own cookies, so this neither moves
    the agent's page nor borrows its session, and it works before the agent
    has signed in.
    """
    # TODO: revisit when session expiry and account lock exist. This signs
    # in on its own, so it will not notice the agent's session expiring,
    # and its sign-ins must not count toward (or be blocked by) a lock.
    context = browser.new_context()
    try:
        page = context.new_page()
        page.set_default_timeout(5000)
        page.goto(f"{base_url}/login")
        page.get_by_label("Username").fill(USERNAME)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign In", exact=True).click()
        page.goto(f"{base_url}/orders")
        return parse_orders(page)
    except PlaywrightError as exc:
        # First line only: the rest is Playwright's call log.
        return Reading(problem=str(exc).splitlines()[0])
    finally:
        context.close()


def _differences(order: Order, goal: Goal) -> str:
    wrong = []
    if order.sku != goal.sku:
        wrong.append(f"SKU {order.sku}, expected {goal.sku}")
    if order.delivery_date != goal.expected_date():
        wrong.append(f"delivery date {order.delivery_date}, expected {goal.expected_date()}")
    return "; ".join(wrong)


def check(before: Reading, after: Reading, goal: Goal) -> Verification:
    """Compare the orders that appeared during a run with what the goal asked for.

    Any new order that does not match the goal makes the run wrong_details,
    even if a correct one was placed too: a wrong order is in the table
    either way. duplicate is kept for the case where every new order is
    right and there is simply more than one of them.
    """
    if before.problem:
        return Verification(UNVERIFIABLE, f"could not read orders before the run: {before.problem}")
    if after.problem:
        return Verification(UNVERIFIABLE, f"could not read orders after the run: {after.problem}")

    already_there = {order.number for order in before.orders}
    new = [order for order in after.orders if order.number not in already_there]
    if not new:
        return Verification(MISSING, "no new order in the orders table")

    wrong = [f"{order.number}: {diff}" for order in new if (diff := _differences(order, goal))]
    if wrong:
        return Verification(WRONG_DETAILS, " | ".join(wrong))
    numbers = ", ".join(sorted(order.number for order in new))
    if len(new) > 1:
        return Verification(DUPLICATE, f"the order was placed {len(new)} times: {numbers}")
    return Verification(VERIFIED, numbers)
