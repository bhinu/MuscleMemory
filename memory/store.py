"""Saved fixes: what a person did to get the agent unstuck, and where.

This is the agent's own database, separate from the portal's orders.db. The
portal never sees it; the agent never opens the portal's.

A fix is stored with:
  page      -- which page it belongs to, as a pattern (see page_key)
  goal      -- what the agent was trying to do at the time
  steps     -- the person's actions, as JSON
  snapshot  -- the page as it looked when the agent got stuck
  landmarks -- what on that page the fix depends on, chosen from the
               snapshot when the fix is saved (see landmarks.py)
  risky     -- indexes of steps replay must not take without a person
               (see risk.py)
"""

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from agent import actions
from memory.landmarks import Landmark, choose
from memory.risk import risky_steps

DB_PATH = Path(__file__).resolve().parent.parent / "memory.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fixes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page TEXT NOT NULL,
    goal TEXT NOT NULL,
    steps TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    landmarks TEXT NOT NULL,
    risky TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

# A path segment with a digit in it is an identifier (SKU-1002, 42, ...),
# not part of the page's identity.
_ID_SEGMENT = re.compile(r"\d")


@dataclass(frozen=True)
class Fix:
    id: int
    page: str
    goal: str
    steps: list[actions.Action]
    snapshot: str
    landmarks: list[Landmark]
    risky: list[int]
    created_at: str


def page_key(url: str) -> str:
    """Which page a URL is, ignoring the host and anything that varies.

    http://127.0.0.1:8000/order/SKU-1002?x=1 -> /order/{id}

    so a fix made while ordering one product applies to every product's
    order form, and the same fix works whichever port the portal runs on.
    """
    segments = urlsplit(url).path.strip("/").split("/")
    return "/" + "/".join("{id}" if _ID_SEGMENT.search(s) else s for s in segments if s)


def _connect() -> sqlite3.Connection:
    # The table is created on connect rather than by a separate init call:
    # the agent, scripts and tests all reach the store, and none of them
    # should have to remember to set it up first.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _to_fix(row: sqlite3.Row) -> Fix:
    return Fix(
        id=row["id"],
        page=row["page"],
        goal=row["goal"],
        steps=[actions.from_payload(step) for step in json.loads(row["steps"])],
        snapshot=row["snapshot"],
        landmarks=[Landmark(**m) for m in json.loads(row["landmarks"])],
        risky=json.loads(row["risky"]),
        created_at=row["created_at"],
    )


def save_fix(
    url: str,
    goal: str,
    steps: list[actions.Action],
    snapshot: str,
    marked_risky: set[int] = frozenset(),
) -> int:
    """Store one fix and return its id.

    marked_risky holds indexes of steps the person flagged as risky, on top
    of the ones risk.py recognises by itself.
    """
    if not steps:
        raise ValueError("a fix needs at least one step")
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO fixes (page, goal, steps, snapshot, landmarks, risky, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                page_key(url),
                goal,
                json.dumps([asdict(step) for step in steps]),
                snapshot,
                json.dumps([asdict(m) for m in choose(snapshot, steps)]),
                json.dumps(risky_steps(steps, marked_risky)),
                created_at,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def fixes_for(url: str) -> list[Fix]:
    """Every fix saved for the page at this URL, newest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM fixes WHERE page = ? ORDER BY id DESC", (page_key(url),)
        ).fetchall()
    finally:
        conn.close()
    return [_to_fix(row) for row in rows]
