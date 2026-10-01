"""Reading what a person types during a takeover. No browser needed."""

import pytest

from agent import actions, human


def test_click_keeps_the_quoted_name_whole():
    action = human.parse('click button "Submit Purchase Request"')
    assert action == actions.Action(
        kind="click", role="button", name="Submit Purchase Request", reason="done by a person"
    )


def test_fill_takes_a_value_after_the_name():
    action = human.parse('fill textbox "Delivery date (DD/MM/YYYY)" 15/10/2026')
    assert action.kind == "fill"
    assert action.name == "Delivery date (DD/MM/YYYY)"
    assert action.value == "15/10/2026"


@pytest.mark.parametrize("line", ["resume", "  RESUME  "])
def test_resume(line):
    assert human.parse(line) == human.RESUME


def test_abort():
    assert human.parse("abort") == human.ABORT


@pytest.mark.parametrize(
    "line",
    [
        "",
        "dance",
        'click button',  # no name
        'fill textbox "Delivery date"',  # no value
        'click button "Place Order',  # unclosed quote
        "resume now",
    ],
)
def test_bad_lines_are_rejected_not_guessed(line):
    with pytest.raises(ValueError):
        human.parse(line)


def test_takeover_keeps_only_the_steps_that_worked():
    """A real browser on an inline page, with typed lines scripted."""
    sync_api = pytest.importorskip("playwright.sync_api")
    lines = iter(
        [
            'click button "Place Order"',  # not on this page: dropped
            'fill textbox "Delivery date" 10/15/2026',
            'click button "Submit Purchase Request"',
            "resume",
        ]
    )
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(500)
        page.set_content(
            '<label for="d">Delivery date</label><input id="d">'
            '<button onclick="this.textContent=\'Sent\'">Submit Purchase Request</button>'
        )
        result = human.take_over(page, "button moved", read=lambda _: next(lines))
        assert page.get_by_role("button", name="Sent").count() == 1
        browser.close()

    assert not result.aborted
    assert [(s.kind, s.name) for s in result.steps] == [
        ("fill", "Delivery date"),
        ("click", "Submit Purchase Request"),
    ]


def test_takeover_with_no_terminal_counts_as_abort():
    sync_api = pytest.importorskip("playwright.sync_api")

    def no_terminal(_):
        raise EOFError

    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<button>Place Order</button>")
        result = human.take_over(page, "stuck", read=no_terminal)
        browser.close()
    assert result.aborted and result.steps == []
