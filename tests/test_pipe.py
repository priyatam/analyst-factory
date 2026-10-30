"""The pipe end to end on the real mocks: clean run, gated run, both decisions, gaps."""
import json

import pytest

from novamark import orchestrator
from novamark import state as store
from novamark.process import evidence_check, gates
from novamark.process.data_collector import RateLimited, quote
from novamark.process.evidence_check import EvidenceError

from tests.support import Model, fields, run, weak_revenue

NVDA = {"request": {"ticker": "NVDA", "asset_class": "equity", "analysis_type": "memo"},
        "run_id": "run-1"}


def test_clean_run_pauses_for_compliance_only(deps):
    """Good evidence, low risk: no senior analyst, straight to compliance."""
    result = run(orchestrator.run(NVDA, deps(Model(fields()))))

    assert result["gate"] == "compliance_review"
    assert result["flagged"] == []
    assert result["memo"] == "MEMO"
    assert store.load("run-1")["status"] == "compliance_review"


def test_low_confidence_run_pauses_for_senior_analyst_first(deps):
    """One weak field: the analyst sees it before any memo is written."""
    result = run(orchestrator.run(NVDA, deps(Model(fields(revenue=weak_revenue())))))

    assert result["gate"] == "senior_review"
    assert result["flagged"] == ["revenue"]
    assert result["values"]["revenue"]["confidence"] == 0.2
    assert result["memo"] is None


def test_high_risk_run_pauses_even_when_every_field_is_confident(deps):
    """Risk alone is enough. The rule reads config, not the prompt."""
    reasons = json.dumps({"reasons": ["Revenue is concentrated among a few customers"]})
    result = run(orchestrator.run(NVDA, deps(Model(fields(), reasons=reasons))))

    assert result["gate"] == "senior_review"
    assert result["risk"]["level"] == "high"
    assert result["flagged"] == []


def test_garbled_unit_is_capped_and_flagged(deps):
    """`$11,900` beside `$115.2 billion`: the model said 0.9, the code says 0.5."""
    shaky = fields(segment_revenue={"value": 11900, "excerpt": "Gaming $11,900",
                                    "confidence": 0.9, "reason": "table", "source_id": "DOC-NVDA-10K"})
    result = run(orchestrator.run(NVDA, deps(Model(shaky))))

    assert result["values"]["segment_revenue"]["confidence"] == 0.5
    assert "no scale unit" in result["values"]["segment_revenue"]["reason"]
    assert result["gate"] == "senior_review"


def test_knowledge_base_failure_is_a_gap_and_the_run_continues(deps):
    """MCP down is a note in the memo, not a dead run."""
    async def broken(ticker):
        raise ConnectionError("kb unreachable")

    result = run(orchestrator.run(NVDA, deps(Model(fields()), kb=broken)))

    assert result["gate"] == "compliance_review"
    assert result["gaps"] == [{"source": "knowledge_base", "reason": "kb unreachable"}]
    assert result["prior_memos"] is None


def test_market_rate_limit_is_a_gap_not_a_crash(deps):
    async def limited(ticker):
        raise RateLimited(after=2)

    result = run(orchestrator.run(NVDA, deps(Model(fields()), quote=limited)))

    assert result["gate"] == "compliance_review"
    assert [g["source"] for g in result["gaps"]] == ["market"]
    saved = store.load("run-1")
    assert "DOC-NVDA-10K" in saved["sources"]
    assert not any(k.startswith("market:") for k in saved["sources"])


def test_approval_at_gate1_continues_to_compliance(deps):
    d = deps(Model(fields(revenue=weak_revenue())))
    run(orchestrator.run(NVDA, d))

    result = run(orchestrator.decide(
        {"run_id": "run-1", "roles": ["senior_analyst"],
         "decision": {"gate": "senior_review", "action": "approve", "reviewer": "pri",
                      "comment": "ok, note the gap"}}, d))

    assert result["gate"] == "compliance_review"
    assert result["memo"] == "MEMO"
    assert store.load("run-1")["decisions"][0]["action"] == "approve"


def test_rejection_at_gate1_revises_the_analysis(deps):
    """Reject goes back to the analyser. A better second answer clears the gate."""
    model = Model([fields(revenue=weak_revenue()), fields()])
    d = deps(model)
    run(orchestrator.run(NVDA, d))
    calls = len(model.prompts)

    result = run(orchestrator.decide(
        {"run_id": "run-1", "roles": ["senior_analyst"],
         "decision": {"gate": "senior_review", "action": "reject", "reviewer": "pri",
                      "comment": "find the segment table"}}, d))

    assert len(model.prompts) > calls
    assert result["gate"] == "compliance_review"
    assert result["values"]["revenue"]["confidence"] == 0.9
    saved = store.load("run-1")
    assert saved["revision"] == 1
    assert saved["decisions"][0]["comment"] == "find the segment table"


def test_rejection_that_does_not_improve_pauses_again(deps):
    """Same weak answer: the analyst sees it a second time instead of a memo."""
    d = deps(Model(fields(revenue=weak_revenue())))
    run(orchestrator.run(NVDA, d))

    result = run(orchestrator.decide(
        {"run_id": "run-1", "roles": ["senior_analyst"],
         "decision": {"gate": "senior_review", "action": "reject", "reviewer": "pri", "comment": "again"}}, d))

    assert result["gate"] == "senior_review"
    assert result["revision"] == 1


def test_amendment_stamps_the_human_and_publishes_after_compliance(deps):
    """Amend carries a human value; compliance approval is what publishes."""
    model = Model(fields(revenue=weak_revenue()))
    d = deps(model)
    run(orchestrator.run(NVDA, d))
    run(orchestrator.decide(
        {"run_id": "run-1", "roles": ["senior_analyst"],
         "decision": {"gate": "senior_review", "action": "amend", "reviewer": "pri", "comment": "fixed",
                      "amended_values": {"revenue": {"value": 130.6, "excerpt": "Revenue for fiscal 2026 was $130.6 billion",
                                                     "confidence": 0.99, "reason": "stated",
                                                     "source_id": "DOC-NVDA-10K"}}}}, d))
    saved = store.load("run-1")
    assert saved["values"]["revenue"]["model_id"] == "human_amend"
    assert saved["values"]["revenue"]["confidence"] == 1.0

    result = run(orchestrator.decide(
        {"run_id": "run-1", "roles": ["compliance_officer"],
         "decision": {"gate": "compliance_review", "action": "approve", "reviewer": "dan", "comment": "ship"}}, d))

    assert result["status"] == "published"
    assert store.load("run-1")["status"] == "published"


def test_an_analyst_cannot_approve_compliance(deps):
    d = deps(Model(fields()))
    run(orchestrator.run(NVDA, d))

    with pytest.raises(PermissionError, match="compliance_officer"):
        run(orchestrator.decide(
            {"run_id": "run-1", "roles": ["analyst"],
             "decision": {"gate": "compliance_review", "action": "approve", "reviewer": "x", "comment": ""}}, d))


def test_revision_cap_escalates(deps):
    """Three rejections, each with its own id, escalate the run."""
    d = deps(Model(fields(revenue=weak_revenue())))
    run(orchestrator.run(NVDA, d))

    result = None
    for n in range(1, 4):
        result = run(orchestrator.decide(
            {"run_id": "run-1", "roles": ["senior_analyst"],
             "decision": {"gate": "senior_review", "action": "reject", "reviewer": "pri",
                          "comment": "again", "id": f"d{n}"}}, d))

    assert result["status"] == "escalated"
    assert result["revision"] == 3


def test_a_replayed_decision_is_not_applied_twice(deps):
    """A client retry after a timeout must not double-count a rejection."""
    d = deps(Model(fields(revenue=weak_revenue())))
    run(orchestrator.run(NVDA, d))
    decision = {"gate": "senior_review", "action": "reject", "reviewer": "pri",
                "comment": "again", "id": "same-id"}

    run(orchestrator.decide({"run_id": "run-1", "roles": ["senior_analyst"],
                             "decision": decision}, d))
    first = store.load("run-1")

    run(orchestrator.decide({"run_id": "run-1", "roles": ["senior_analyst"],
                             "decision": decision}, d))
    second = store.load("run-1")

    assert first["revision"] == second["revision"] == 1
    assert len(first["decisions"]) == len(second["decisions"]) == 1


def test_a_value_needs_both_a_citation_and_a_confidence(deps):
    """The requirement is one field, one citation, one confidence. Either missing fails."""
    no_citation = fields(revenue={"value": 1, "excerpt": "", "confidence": 0.9, "reason": "",
                                  "source_id": "DOC-NVDA-10K"})
    no_confidence = fields(revenue={"value": 1, "excerpt": "Gross margin was 74.6%",
                                    "confidence": None, "reason": "",
                                    "source_id": "DOC-NVDA-10K"})
    neither = fields(revenue={"value": 1, "excerpt": "", "confidence": None, "reason": "",
                              "source_id": "DOC-NVDA-10K"})

    for bad in (no_citation, no_confidence, neither):
        with pytest.raises(EvidenceError, match="both a citation and a confidence"):
            run(orchestrator.run(NVDA, deps(Model(bad))))


def test_a_metric_the_text_never_mentions_is_omitted(deps):
    """An unmentioned metric is not a finding. A stated figure can still go straight to compliance."""
    absent = fields(capex_outlook={"value": None, "excerpt": "", "confidence": None,
                                   "reason": "not stated", "source_id": ""})

    result = run(orchestrator.run(NVDA, deps(Model(absent))))

    assert "capex_outlook" not in result["values"]
    assert result["gate"] == "compliance_review"


def test_invented_citation_fails_closed(deps):
    """An excerpt that is not in the source cannot be shipped to a reviewer."""
    fake = fields(revenue={"value": 1, "excerpt": "Revenue was $999 billion", "confidence": 0.95,
                           "reason": "stated", "source_id": "DOC-NVDA-10K"})

    with pytest.raises(EvidenceError, match="not found in source"):
        run(orchestrator.run(NVDA, deps(Model(fake))))


def test_retrying_honours_the_servers_wait_and_gives_up(deps):
    """The mock's 429 says Retry-After: 2. We wait what it says, then stop."""
    waits, calls = [], 0

    async def flaky(*_):
        nonlocal calls
        calls += 1
        raise RateLimited(after=2)

    async def sleep(seconds):
        waits.append(seconds)

    async def attempt():
        await quote(send=flaky, times=3, sleep=sleep)("NVDA")

    with pytest.raises(RateLimited):
        run(attempt())
    assert calls == 3
    assert waits == [2, 2]


def test_a_retried_call_succeeds_after_one_rate_limit(deps):
    calls = 0

    async def flaky(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RateLimited(after=2)
        return {"data": {"pe_ratio": 52.7}, "as_of": "2026-10-29T00:00:00Z"}

    async def sleep(_):
        return None

    assert run(quote(send=flaky, sleep=sleep)("NVDA"))["data"]["pe_ratio"] == 52.7
    assert calls == 2
