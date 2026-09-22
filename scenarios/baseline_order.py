"""A hardcoded Playwright run: log in and place one order.

No LLM anywhere. This is the control case -- the brittle version whose failure
motivates the rest of the project. It knows the exact wording of every control
it touches, which works perfectly until the site changes its mind.

Start the portal first:
    uvicorn portal.app:app

Then:
    python scenarios/baseline_order.py          # headless
    HEADED=1 python scenarios/baseline_order.py # watch it drive
"""

import os
import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("PORTAL_URL", "http://127.0.0.1:8000")
SKU = "SKU-1002"
DELIVERY_DATE = "10/15/2026"  # MM/DD/YYYY, the unmutated portal's format


def place_order(page) -> str:
    """Drive the four pages and return the order number."""
    # 1. Sign in. get_by_label walks from the visible <label> to the input it
    #    is bound to, so this survives the field being renamed or moved --
    #    but not the label text changing.
    page.goto(f"{BASE_URL}/login")
    page.get_by_label("Username").fill("buyer")
    page.get_by_label("Password").fill("hunter2")
    page.get_by_role("button", name="Sign In").click()

    # 2. Find the product's row by its SKU, then the Order link inside it.
    #    Scoping to the row is what stops us ordering the wrong product.
    row = page.get_by_role("row").filter(has_text=SKU)
    row.get_by_role("link", name="Order").click()

    # 3. Fill the form and submit.
    page.get_by_label("Delivery date").fill(DELIVERY_DATE)
    page.get_by_role("button", name="Place Order").click()

    # 4. Read the order number off the confirmation page.
    page.get_by_role("heading", name="Order Confirmed").wait_for()
    row = page.get_by_role("row").filter(has_text="Order number")
    return row.locator("td").inner_text()


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not os.environ.get("HEADED"))
        page = browser.new_page()
        # Fail fast. The 30s default is a long time to watch nothing happen.
        page.set_default_timeout(5000)
        try:
            number = place_order(page)
        except PlaywrightTimeoutError as exc:
            print("FAILED -- the script could not find something it expected:\n")
            print("\n".join(str(exc).splitlines()[:6]))
            return 1
        finally:
            browser.close()
    print(f"OK -- placed {number}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
