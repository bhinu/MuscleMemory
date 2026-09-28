"""Ask the model for the next action.

The model gets the goal, what has happened so far, and the current page as an
accessibility tree. It returns one action from the fixed vocabulary -- enforced
by the API through a strict JSON schema, not by asking politely.
"""

import json
import os

from openai import OpenAI

from agent import actions

DEFAULT_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are operating a website through a browser. You cannot \
see pixels. You see the page's accessibility tree, which lists each control's \
role and its accessible name.

Reply with exactly one action:
  click - press a control. Give its role and its exact accessible name.
  fill  - type into a field. Give its role, exact accessible name, and value.
  done  - the goal is complete, and the page in front of you shows that.
  stuck - you cannot work out the next step, or the page is not what you
          expected. Explain why in reason.

Rules:
- Copy role and name exactly from the snapshot. Never invent or paraphrase them.
- Take one step at a time. You will see the resulting page before deciding again.
- Prefer stuck over guessing. A wrong click here can place a real order, and a
  wrong guess is worse than stopping.
- reason is one short sentence saying why you chose this action."""


def decide(goal: str, snapshot: str, history: list[str]) -> actions.Action:
    """One round trip: page in, single action out."""
    done_so_far = "\n".join(f"- {line}" for line in history) or "(nothing yet)"
    user_prompt = (
        f"Goal: {goal}\n\n"
        f"What you have done so far:\n{done_so_far}\n\n"
        f"The page right now:\n{snapshot}"
    )
    # Read at call time, not import time, so a .env loaded by the caller counts.
    response = OpenAI().chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "action",
                "strict": True,
                "schema": actions.SCHEMA,
            },
        },
    )
    return actions.from_payload(json.loads(response.choices[0].message.content))
