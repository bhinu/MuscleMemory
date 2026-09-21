"""Order storage for the portal.

This database belongs to the portal alone. It is the site's own records --
the agent reaches it only by loading pages over HTTP, never by opening this
file. The agent's memory of fixes lives in a separate database.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "orders.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    product_name TEXT NOT NULL,
    delivery_date TEXT NOT NULL,
    placed_at TEXT NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def order_number(order_id: int) -> str:
    """Render a row id as the order number shown to users: 7 -> ORD-00007."""
    return f"ORD-{order_id:05d}"


def init_db() -> None:
    conn = _connect()
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save_order(sku: str, product_name: str, delivery_date: str) -> str:
    """Store one order and return its order number."""
    placed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO orders (sku, product_name, delivery_date, placed_at)"
            " VALUES (?, ?, ?, ?)",
            (sku, product_name, delivery_date, placed_at),
        )
        conn.commit()
        return order_number(cursor.lastrowid)
    finally:
        conn.close()


def list_orders() -> list[dict]:
    """Every order, newest first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, sku, product_name, delivery_date, placed_at"
            " FROM orders ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()
    return [{**dict(row), "order_number": order_number(row["id"])} for row in rows]
