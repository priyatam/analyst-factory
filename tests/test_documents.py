"""The two messy documents in the pack: a garbled unit and a claim nobody quantified."""
from novamark import orchestrator
from novamark.process.document_analyser import unscaled

from tests.support import Model, run


def test_supplier_concentration_is_not_the_severe_rule():
    """AAPL's suppliers are 'concentrated with'. That is not customer concentration."""
    from novamark.process.risk_assessor import level

    suppliers = level(["Manufacturing is concentrated with a small number of suppliers"],
                      {"revenue": {"confidence": 0.94}})
    customers = level(["Revenue is concentrated among a few customers"],
                      {"revenue": {"confidence": 0.94}})

    assert suppliers["level"] == "medium"
    assert customers["level"] == "high"


def test_an_unmentioned_metric_is_not_a_decline():
    from novamark.process.document_analyser import declined

    assert not declined({"value": None, "excerpt": "", "reason": "not in the filing"})
    assert declined({"value": None, "excerpt": "We're not breaking that out separately yet", "reason": ""})


def test_nvda_segment_figure_is_capped_because_it_has_no_scale():
    """The table puts a scaled and an unscaled amount in the same column."""
    assert not unscaled("Data Center $115.2 billion")  # scaled: comparable
    assert unscaled("Gaming $11,900")                  # the garble: no unit
    assert not unscaled("Gross margin was 74.6%")      # a percentage, not an amount


def test_msft_copilot_claim_stays_null_and_goes_to_a_human(deps):
    """The document says it will not break Copilot out. Null stays null, low confidence."""
    claim = {"revenue": {"value": 69.6, "excerpt": "Revenue was $69.6 billion, up 12% year over year",
                         "confidence": 0.93, "reason": "stated by the CFO", "source_id": "DOC-MSFT-CALL"},
             "copilot_contribution": {"value": None, "excerpt": "We're not breaking that out separately yet",
                                      "confidence": 0.2, "reason": "management declined to quantify",
                                      "source_id": "DOC-MSFT-CALL"}}
    msft = {"request": {"ticker": "MSFT", "asset_class": "equity", "analysis_type": "memo"},
            "run_id": "msft-1"}

    result = run(orchestrator.run(msft, deps(Model(_json(claim)), kb=[])))

    assert result["gate"] == "senior_review"
    assert result["flagged"] == ["copilot_contribution"]
    assert result["values"]["copilot_contribution"]["value"] is None


def test_a_figure_that_is_not_stated_carries_no_citation():
    """The model sometimes quotes an unrelated sentence for a null value; that is not evidence."""
    from novamark.process.document_analyser import entry

    got = entry({"value": None, "excerpt": "The Company depends on third-party foundries.",
                 "confidence": 0.05, "reason": "not stated", "source_id": "DOC-NVDA-10K"})

    assert got["value"] is None
    assert got["excerpt"] == "" and got["source_id"] == ""
    assert got["reason"] == "not stated"


def _json(fields: dict) -> str:
    import json

    return json.dumps({"values": fields})
