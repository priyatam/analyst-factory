"""The live display, without calling the runtime."""
import json

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


def test_the_demo_runs_the_clean_filing_unless_high_risk_is_set():
    from demo import arguments, selected

    assert selected(False) == (("tidy filing", "AAPL"),)
    assert selected(True) == (("high risk filing", "NVDA"),)
    parsed = arguments().parse_args(["--auto-approve", "--high-risk"])
    assert parsed.auto_approve and parsed.high_risk
    assert arguments().parse_args([]).auto_approve is False


def test_the_audit_flag_parses_and_does_not_approve():
    from demo import arguments

    parsed = arguments().parse_args(["--audit"])

    assert parsed.audit is True
    assert parsed.auto_approve is False
    assert parsed.high_risk is False
    assert arguments().parse_args([]).audit is False


def test_the_audit_view_includes_the_run_the_status_and_a_metric():
    from cli import show_state

    console = Console(width=120, force_terminal=True, record=True)
    show_state({"run_id": "run-9", "status": "published", "revision": 0,
                "request": {"ticker": "AAPL"}, "sources": {},
                "values": {"revenue": {"value": 391.0, "confidence": 0.91, "excerpt": "net sales"}},
                "risk": None, "prior_memos": None, "gaps": [], "freshness": {},
                "decisions": [], "memo": None, "applied": []}, console)

    text = console.export_text()
    assert "run-9" in text
    assert "published" in text
    assert "revenue" in text


def test_the_audit_trace_is_read_from_cloudwatch_and_printed_as_spans():
    from cli import fetch_trace, show_trace

    class Logs:
        def filter_log_events(self, **kwargs):
            pattern = kwargs["filterPattern"]
            runtime = "arn:aws:bedrock-agentcore:us-west-2:1:runtime/novamark_research-id"
            resource = {"attributes": {"cloud.resource_id": runtime, "service.name": "novamark"}}
            if pattern == '"run-9"' and kwargs["logGroupName"].endswith("-DEFAULT"):
                return {"events": [{"message": json.dumps({
                    "name": "advance", "traceId": "trace-1", "spanId": "span-a",
                    "resource": resource,
                    "attributes": {"run_id": "run-9", "status": "document_analyser", "revision": 0},
                    "startTimeUnixNano": "1000000000", "endTimeUnixNano": "1600000000"})}]}
            if pattern == '"trace-1"' and kwargs["logGroupName"] == "aws/spans":
                return {"events": [
                    {"message": json.dumps({
                        "name": "chat", "traceId": "trace-1", "spanId": "span-b",
                        "parentSpanId": "span-a", "resource": resource,
                        "attributes": {"gen_ai.request.model": "us.anthropic.claude-sonnet-4-6",
                                       "gen_ai.usage.input_tokens": 592,
                                       "gen_ai.usage.output_tokens": 442},
                        "startTimeUnixNano": "1100000000", "endTimeUnixNano": "1500000000"})},
                    {"message": json.dumps({
                        "name": "GET /api/v1/market/quote", "traceId": "trace-1", "spanId": "span-c",
                        "parentSpanId": "span-a", "resource": resource,
                        "attributes": {"http.status_code": 200},
                        "startTimeUnixNano": "1050000000", "endTimeUnixNano": "1200000000"})},
                    {"message": json.dumps({
                        "name": "fastapi.endpoint", "traceId": "trace-1", "spanId": "span-d",
                        "startTimeUnixNano": "1060000000", "endTimeUnixNano": "1070000000"})},
                ]}
            return {"events": []}

    events = fetch_trace("arn:aws:bedrock-agentcore:us-west-2:1:runtime/novamark_research-id",
                         "run-9", client=Logs())
    console = Console(width=200, force_terminal=True, record=True)
    show_trace(events, console)
    text = console.export_text()

    assert "CloudWatch Logs" in text
    header = next(line for line in text.splitlines() if "identity" in line and "action" in line)
    assert header.index("identity") < header.index("action")
    assert "Identity: arn:aws:bedrock-agentcore:us-west-2:1:runtime/novamark_research-id" in text
    assert "(alias=novamark)" in text
    assert text.index("Identity:") < text.index(header)
    assert "novamark" in text
    assert "document_analyser" in text
    assert "model" in text
    assert "Tokens: 592 in, 442 out" in text
    assert "592 in, 442 out" in text
    assert "revision 0" in text
    assert "GET /api/v1/market/quote" in text
    assert "fastapi" not in text
    assert "600" in text


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
