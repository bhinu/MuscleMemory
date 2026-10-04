"""Hand the browser to a person when the agent is stuck.

The person drives with the same verbs the model has, typed against the same
accessibility snapshot the model saw:

    click button "Place Order"
    fill textbox "Delivery date (MM/DD/YYYY)" 10/15/2026
    look        -- show the page again
    risky       -- mark the step you just took as one a replay must not
                   take without asking (placing an order is caught anyway)
    resume      -- give control back to the agent
    abort       -- end the run

Their steps come back as ordinary Actions. That is the point: what a person
did is then in exactly the form the agent already knows how to replay.
"""

import shlex
from dataclasses import dataclass, field

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from agent import actions, browser

RESUME = "resume"
ABORT = "abort"
RISKY = "risky"

HELP = """Commands:
  click <role> "<name>"
  fill <role> "<name>" <value>
  look     show the page again
  risky    mark your last step as never to be replayed without asking
  resume   hand control back to the agent
  abort    end the run"""


@dataclass
class Takeover:
    """What happened while a person had the browser."""

    steps: list[actions.Action] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    marked_risky: set[int] = field(default_factory=set)  # indexes into steps
    aborted: bool = False


def parse(line: str) -> actions.Action | str:
    """Turn one typed line into an Action, or RESUME / ABORT / RISKY.

    Raises ValueError with a message meant for the person at the keyboard.
    """
    try:
        words = shlex.split(line)
    except ValueError as exc:
        raise ValueError(f"could not read that line ({exc}) -- check your quotes") from None
    if not words:
        raise ValueError("type a command, or 'help'")
    verb, args = words[0].lower(), words[1:]

    if verb in (RESUME, ABORT, RISKY) and not args:
        return verb
    if verb == actions.CLICK and len(args) == 2:
        payload = {"kind": actions.CLICK, "role": args[0], "name": args[1]}
    elif verb == actions.FILL and len(args) == 3:
        payload = {"kind": actions.FILL, "role": args[0], "name": args[1], "value": args[2]}
    else:
        raise ValueError(f"not a command: {line!r}")
    return actions.from_payload({**payload, "reason": "done by a person"})


def take_over(page: Page, why: str, read=input) -> Takeover:
    """Let a person drive until they type resume or abort.

    Only steps that actually worked are kept: a typo'd name that matched
    nothing is not part of the fix. read is input() in real use; tests pass
    a stand-in. Running out of input (no terminal attached) counts as abort.
    """
    result = Takeover()
    print(f"\nThe agent is stuck: {why}")
    print("You have the browser. The page right now:\n")
    print(browser.snapshot(page))
    print(f"\n{HELP}\n")

    while True:
        try:
            line = read("you> ")
        except EOFError:
            result.aborted = True
            return result
        if line.strip().lower() == "help":
            print(HELP)
            continue
        if line.strip().lower() == "look":
            print(browser.snapshot(page))
            continue
        try:
            command = parse(line)
        except ValueError as exc:
            print(f"  {exc}")
            continue

        if command == ABORT:
            result.aborted = True
            return result
        if command == RESUME:
            return result
        if command == RISKY:
            if not result.steps:
                print("  nothing to mark yet -- take a step first")
            else:
                result.marked_risky.add(len(result.steps) - 1)
                print(f"  marked risky: {result.outcomes[-1].removeprefix('a person ')}")
            continue

        try:
            outcome = browser.execute(page, command)
        except PlaywrightTimeoutError:
            print(f"  nothing on this page is a {command.role} named {command.name!r}")
            continue
        print(f"  {outcome}")
        result.steps.append(command)
        result.outcomes.append(f"a person {outcome}")


def confirm(question: str, read=input) -> bool:
    """Ask a yes/no question. Anything but yes is no, and so is no terminal."""
    try:
        answer = read(f"\n{question} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")
