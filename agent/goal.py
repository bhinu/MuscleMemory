"""What a run is trying to do, stated once.

The model needs the goal as a sentence. Verification needs it as values to
compare against the orders table. Both are produced from the same Goal, so
the sentence can never ask for one thing while the check expects another.
"""

from dataclasses import dataclass
from datetime import date

USERNAME = "buyer"
PASSWORD = "hunter2"


@dataclass(frozen=True)
class Goal:
    """One order to place.

    delivery_date is a real date, not a string: the portal's form may want
    MM/DD or DD/MM, but which day is meant is not up for interpretation.
    """

    sku: str
    product_name: str
    delivery_date: date

    def sentence(self) -> str:
        """The goal as the model reads it.

        The wording is load-bearing: saved fixes are matched on this exact
        text (memory/replay.py), so rewording it orphans every fix recorded
        under the old one. The date is written MM/DD/YYYY, the unmutated
        portal's format.
        """
        return (
            f"Sign in with username '{USERNAME}' and password '{PASSWORD}'. Then order the "
            f"product with {self.sku} ({self.product_name}) for delivery on "
            f"{self.delivery_date.strftime('%m/%d/%Y')}, and "
            "confirm the order was placed."
        )

    def expected_date(self) -> str:
        """The delivery date as the orders table stores it: 2026-10-15."""
        return self.delivery_date.isoformat()
