"""The live display, without calling the runtime."""
import pytest
from rich.console import Console

from cli import blank, observe, screen, track
from novamark.state import Status


def _text(view) -> str:
    console = Console(width=120, force_terminal=True, record=True)
    console.print(screen(view))
    return console.export_text()


def test_a_senior_review_marks_the_earlier_states_done_and_lists_the_flagged_metric():
    view = blank("NVDA", "garbled filing")
    view["waiting"] = ""
    observe(view, {"gate": "senior_review", "role": "senior_analyst", "flagged": ["segment_revenue"],
                   "risk": {"level": "high", "reasons": ["customer concentration"]}, "gaps": [],
                   "values": {"segment_revenue": {"value": 11900, "confidence": 0.5,
                                                  "excerpt": "Gaming $11,900"}}})

    text = _text(view)

    assert view["current"] == Status.SENIOR_REVIEW
    assert Status.DATA_COLLECTOR in view["done"]
    assert "segment_revenue" in text
    assert "Gaming $11,900" in text


def test_a_structured_value_is_shown_as_text():
    view = blank("AAPL", "tidy filing")
    view["waiting"] = ""
    observe(view, {"gate": "senior_review", "role": "senior_analyst", "flagged": [],
                   "risk": {"level": "low", "reasons": []}, "gaps": [],
                   "values": {"revenue": {"value": '{"amount": 402.3, "unit": "USD"}',
                                          "confidence": 0.9, "excerpt": "Net sales were $402.3 billion"},
                              "cloud_revenue": {"value": None, "confidence": 0.1, "excerpt": ""}}})

    text = _text(view)

    assert "amount: 402.3" in text
    assert "unit: USD" in text
    assert "not stated" in text
    assert "{" not in text and "}" not in text


def test_reaching_compliance_without_a_senior_review_marks_that_gate_skipped():
    view = blank("AAPL", "tidy filing")
    observe(view, {"gate": "compliance_review", "role": "compliance_officer", "flagged": [],
                   "risk": {"level": "low", "reasons": []}, "gaps": [], "values": {}})

    assert Status.SENIOR_REVIEW in view["skipped"]
    assert Status.SYNTHESIS in view["done"]
    assert view["current"] == Status.COMPLIANCE_REVIEW


def test_a_rejected_gate_is_red():
    view = blank("NVDA", "garbled filing")
    view["current"] = Status.SENIOR_REVIEW
    view["rejected"] = {Status.SENIOR_REVIEW}

    boxes = track(view).renderable.renderables

    assert boxes[2].border_style == "red"
    assert boxes[4].border_style != "red"


def test_a_rejection_is_explained_before_the_next_prompt():
    from demo import again

    senior = again("senior_review")
    compliance = again("compliance_review")

    assert "extracted the figures again" in senior
    assert "scores can differ" in senior
    assert "same figures" in compliance
    assert "scores are unchanged" in compliance


def test_a_review_answer_needs_an_action_and_a_name():
    from demo import decision

    assert decision("approve", " pri ", "ok") == {"action": "approve", "reviewer": "pri", "comment": "ok"}
    with pytest.raises(ValueError):
        decision("skip", "pri", "")
    with pytest.raises(ValueError):
        decision("reject", "  ", "")


def test_a_published_memo_is_the_current_state():
    view = blank("AAPL", "tidy filing")
    observe(view, {"gate": "compliance_review", "role": "compliance_officer", "flagged": [],
                   "risk": {"level": "low", "reasons": []}, "gaps": [], "values": {}})
    observe(view, {"status": "published", "memo": "AAPL investment memo", "decisions": [{}, {}]})

    text = _text(view)

    assert view["current"] == Status.PUBLISHED
    assert "AAPL investment memo" in text
    assert "2 decisions" in text
