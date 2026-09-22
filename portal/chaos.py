"""Deliberate mutations to the portal.

A mutation is a named change to the site, the kind a real supplier might ship
without warning: a renamed button, a moved field, an extra step. Which ones are
switched on is read from chaos.json, which lives outside the HTTP surface on
purpose -- the agent must not be able to find an endpoint that turns the
obstacle off.
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "chaos.json"

MUTATIONS = {
    "submit_button_moved": (
        "Order form: renames the submit button to 'Submit Purchase Request' and "
        "moves it above the delivery date field."
    ),
}


def active() -> set[str]:
    """Names of the mutations currently switched on.

    Read fresh on every call, so chaos.json can be edited while the portal is
    running. An unknown name is an error rather than a silent no-op: a typo
    that quietly disables a mutation is a long afternoon.
    """
    if not CONFIG_PATH.exists():
        return set()
    names = set(json.loads(CONFIG_PATH.read_text()).get("active", []))
    unknown = names - MUTATIONS.keys()
    if unknown:
        raise ValueError(
            f"Unknown mutation(s) in {CONFIG_PATH.name}: {', '.join(sorted(unknown))}."
            f" Known mutations: {', '.join(sorted(MUTATIONS))}"
        )
    return names
