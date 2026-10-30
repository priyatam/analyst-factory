"""The deployed surface: `agent.invoke`, dispatched on payload type.

These drive the same entrypoint AgentCore calls, with the model and the market swapped for
fakes. Everything else is real: the filings CSV, the MCP subprocess, the state store, the
state machine. No network, no Bedrock.
"""
import asyncio

import pytest

from novamark import agent, knowledge_base, model, orchestrator
from novamark import state as store
from novamark.process import data_collector

from tests.support import Model, fields, run, weak_revenue

NVDA = {"ticker": "NVDA", "asset_class": "equity", "analysis_type": "memo"}


@pytest.fixture
def runtime(deps, monkeypatch):
    """Point the deployed entrypoint at fakes, as the runtime would with real ones."""

    def install(model: Model, quote=None, kb=None) -> dict:
        d = deps(model, quote=quote, kb=kb)
        monkeypatch.setattr(orchestrator, "_deps", lambda: d)
        return d

    return install


def test_new_request_runs_to_a_review_and_saves(runtime):
    """The first call runs the machine until a person is needed, then returns the packet."""
    runtime(Model(fields(revenue=weak_revenue())))

    packet = agent.invoke({"type": "new_request", "request": NVDA})

    assert packet["gate"] == "senior_review"
    assert packet["role"] == "senior_analyst"
    assert packet["flagged"] == ["revenue"]
    assert store.load(packet["run_id"])["status"] == "senior_review"


def test_decision_resumes_the_saved_run_through_to_published(runtime):
    """The second and third calls are the same entrypoint with a different payload type."""
    runtime(Model(fields(revenue=weak_revenue())))
    packet = agent.invoke({"type": "new_request", "request": NVDA})
    run_id = packet["run_id"]

    packet = agent.invoke({"type": "decision", "run_id": run_id, "roles": ["senior_analyst"],
                           "decision": {"gate": "senior_review", "action": "approve",
                                        "reviewer": "pri", "comment": "ok", "id": "d1"}})
    assert packet["gate"] == "compliance_review"

    done = agent.invoke({"type": "decision", "run_id": run_id, "roles": ["compliance_officer"],
                         "decision": {"gate": "compliance_review", "action": "approve",
                                      "reviewer": "dan", "comment": "ship", "id": "d2"}})
    assert done["status"] == "published"
    assert done["memo"]


def test_a_clean_run_reaches_compliance_without_a_senior_review(runtime):
    """High confidence and low risk skip the first person, which is the documented branch."""
    runtime(Model(fields()))

    packet = agent.invoke({"type": "new_request", "request": NVDA})

    assert packet["gate"] == "compliance_review"
    assert packet["flagged"] == []


def test_the_store_holds_one_snapshot_per_review(runtime):
    """Append-only: each review writes a new key and leaves the earlier ones intact."""
    runtime(Model(fields()))
    packet = agent.invoke({"type": "new_request", "request": NVDA})
    agent.invoke({"type": "decision", "run_id": packet["run_id"],
                  "roles": ["compliance_officer"],
                  "decision": {"gate": "compliance_review", "action": "approve",
                               "reviewer": "dan", "comment": "ship", "id": "d1"}})

    snapshots = store.snapshots(packet["run_id"])

    assert [s.split("-", 1)[1] for s in snapshots] == [
        "compliance_review.json", "published.json"]


def test_an_unknown_payload_type_is_a_key_error(runtime):
    runtime(Model(fields()))

    with pytest.raises(KeyError):
        agent.invoke({"type": "reanalyse"})


def test_the_market_gap_does_not_stop_the_run(runtime):
    """A mock market that is down still produces a memo, with the gap recorded."""
    async def down(ticker):
        raise ConnectionError("market unreachable")

    runtime(Model(fields()), quote=down)

    packet = agent.invoke({"type": "new_request", "request": NVDA})

    assert packet["gate"] == "compliance_review"
    assert [g["source"] for g in packet["gaps"]] == ["market"]


def test_the_knowledge_base_is_read_through_the_real_mcp_server(runtime):
    """The real stdio subprocess, resolved from `model.KB_COMMAND` rather than a fake."""
    runtime(Model(fields()))
    memos = run(knowledge_base.history("NVDA"))

    assert len(memos) == 3
    assert {"analyst", "date", "recommendation"} <= set(memos[0])


def test_the_filings_are_read_from_the_shipped_data_dir(runtime):
    """DATA_DIR has to resolve identically in the repo and in the runtime zip."""
    assert (model.DATA_DIR / "filings_metadata.csv").exists()
    assert data_collector.filings("NVDA")
