"""Saving and loading fixes. Each test gets its own throwaway database."""

import pytest

from agent import actions
from memory import store

STEPS = [
    actions.Action(kind="fill", role="textbox", name="Delivery date (MM/DD/YYYY)",
                   value="10/15/2026", reason="done by a person"),
    actions.Action(kind="click", role="button", name="Submit Purchase Request",
                   reason="done by a person"),
]


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.db")


@pytest.mark.parametrize(
    "url, key",
    [
        ("http://127.0.0.1:8000/order/SKU-1002", "/order/{id}"),
        ("http://localhost:9999/order/SKU-1003?ref=x#top", "/order/{id}"),
        ("http://127.0.0.1:8000/products", "/products"),
        ("http://127.0.0.1:8000/", "/"),
        ("http://127.0.0.1:8000/orders/42/edit", "/orders/{id}/edit"),
    ],
)
def test_page_key(url, key):
    assert store.page_key(url) == key


def test_a_saved_fix_comes_back_exactly():
    fix_id = store.save_fix(
        "http://127.0.0.1:8000/order/SKU-1002", "order a widget", STEPS, "- button \"x\""
    )
    [fix] = store.fixes_for("http://127.0.0.1:8000/order/SKU-1002")
    assert fix.id == fix_id
    assert fix.page == "/order/{id}"
    assert fix.goal == "order a widget"
    assert fix.steps == STEPS
    assert fix.snapshot == '- button "x"'


def test_a_fix_applies_to_every_product_but_not_other_pages():
    store.save_fix("http://127.0.0.1:8000/order/SKU-1002", "goal", STEPS, "")
    assert len(store.fixes_for("http://127.0.0.1:8000/order/SKU-1003")) == 1
    assert store.fixes_for("http://127.0.0.1:8000/products") == []


def test_newest_fix_first():
    url = "http://127.0.0.1:8000/order/SKU-1002"
    first = store.save_fix(url, "goal", STEPS, "")
    second = store.save_fix(url, "goal", STEPS[:1], "")
    assert [f.id for f in store.fixes_for(url)] == [second, first]


def test_an_empty_fix_is_refused():
    with pytest.raises(ValueError):
        store.save_fix("http://127.0.0.1:8000/products", "goal", [], "")
