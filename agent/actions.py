"""The complete set of things the agent is allowed to do.

The model never writes code. It picks one of four verbs and fills in the
arguments. This module is the only place that list exists: the JSON schema
sent to the model and the executor that carries actions out both read from
here, so the two can never drift apart.
"""

from dataclasses import dataclass

CLICK = "click"
FILL = "fill"
DONE = "done"
STUCK = "stuck"


@dataclass(frozen=True)
class Action:
    """One decision from the model.

    role and name are copied from the accessibility tree, so an Action is a
    plain value -- serialisable, comparable, and storable. That is what will
    make it possible to save one as a fix later.
    """

    kind: str
    role: str = ""
    name: str = ""
    value: str = ""
    reason: str = ""


# Sent to the model as a strict JSON schema. Strict mode requires every
# property to be listed in "required", so unused fields come back as "".
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": [CLICK, FILL, DONE, STUCK]},
        "role": {"type": "string", "description": "ARIA role, e.g. button, textbox, link"},
        "name": {"type": "string", "description": "exact accessible name from the snapshot"},
        "value": {"type": "string", "description": "text to type, for fill only"},
        "reason": {"type": "string", "description": "one sentence: why this action"},
    },
    "required": ["kind", "role", "name", "value", "reason"],
    "additionalProperties": False,
}


def from_payload(payload: dict) -> Action:
    """Build an Action from the model's JSON, rejecting incoherent ones.

    The schema pins the vocabulary but cannot express "name is required when
    kind is click", so that part is checked here.
    """
    action = Action(
        kind=payload["kind"],
        role=payload.get("role", ""),
        name=payload.get("name", ""),
        value=payload.get("value", ""),
        reason=payload.get("reason", ""),
    )
    if action.kind in (CLICK, FILL) and not (action.role and action.name):
        raise ValueError(f"{action.kind} needs both a role and a name, got {action}")
    if action.kind == FILL and not action.value:
        raise ValueError(f"fill needs a value, got {action}")
    return action
