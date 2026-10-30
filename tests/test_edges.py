"""The real edges, not fakes: MCP over stdio, the market mock's 429, the entrypoint."""
import asyncio

import httpx
import pytest

from novamark import agent, knowledge_base, model, orchestrator
from novamark.process import data_collector
from novamark.state import MemoState


def test_mcp_knowledge_base_reads_prior_memos_over_stdio():
    """The real stdio MCP server, the resource the requirement names."""
    memos = asyncio.run(knowledge_base.history("NVDA"))

    assert len(memos) == 3
    assert {"analyst", "date", "thesis", "recommendation"} <= set(memos[0])
    assert any("supply" in m["thesis"].lower() for m in memos)


def test_mcp_failure_becomes_a_gap_through_the_real_router():
    """Point the command at nothing; the run records a gap instead of raising."""
    state = {"request": {"ticker": "NVDA"}, "gaps": [], "prior_memos": None}
    deps = {"kb": lambda ticker: _boom()}

    after = asyncio.run(knowledge_base.prior_research(state, deps))

    assert after["prior_memos"] is None
    assert after["gaps"][0]["source"] == "knowledge_base"


def test_merge_keeps_each_branchs_work_and_every_gap():
    """Two branches from one state: each key comes from the branch that changed it."""
    base = {"sources": {}, "prior_memos": None, "status": "data_collector",
            "gaps": [{"source": "old", "reason": ""}]}
    market = {**base, "sources": {"a": "text"}, "status": "document_analyser",
              "gaps": [*base["gaps"], {"source": "market", "reason": ""}]}
    kb = {**base, "prior_memos": [1], "gaps": [*base["gaps"], {"source": "kb", "reason": ""}]}

    out = orchestrator.merge(base, market, kb)

    assert (out["sources"], out["prior_memos"], out["status"]) == (
        {"a": "text"}, [1], "document_analyser")
    assert [g["source"] for g in out["gaps"]] == ["old", "market", "kb"]


async def _boom():
    raise ConnectionError("kb unreachable")


@pytest.mark.parametrize("ticker", ["NVDA", "AAPL", "MSFT"])
def test_filings_index_reads_the_real_csv(ticker):
    docs = data_collector.filings(ticker)

    assert len(docs) == 1
    doc = next(iter(docs.values()))
    assert doc["ticker"] == ticker
    assert len(doc["text"]) > 400


def test_market_mock_rate_limits_every_fifth_call_and_says_how_long():
    """The mock's contract, read through its own ASGI app."""
    from mocks.mock_market_data_api import VALID_TOKEN, app

    async def call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
            r = await c.get("/api/v1/market/quote", params={"ticker": "NVDA", "fields": "price"},
                            headers={"Authorization": f"Bearer {VALID_TOKEN}"})
            return r.status_code, r.headers.get("Retry-After")

    results = [asyncio.run(call()) for _ in range(5)]

    assert [code for code, _ in results] == [200, 200, 200, 200, 429]
    assert results[-1][1] == "2"


def test_quote_raises_rate_limited_with_the_servers_wait(monkeypatch):
    """The client turns the mock's 429 into `RateLimited(after=2)`, not a bare error."""
    from novamark.process.data_collector import RateLimited

    class Response:
        status_code, headers = 429, {"Retry-After": "2"}
        def raise_for_status(self): ...
        def json(self): return {}

    monkeypatch.setattr(data_collector.model, "MARKET_API_URL", "http://market")
    monkeypatch.setattr(data_collector.httpx, "get", lambda *a, **k: Response())

    with pytest.raises(RateLimited) as caught:
        asyncio.run(data_collector.quote_once("NVDA"))
    assert caught.value.after == 2.0


def test_entrypoint_dispatches_both_payloads(monkeypatch):
    """`invoke` routes on type, and the pipeline is imported lazily on first call."""
    from novamark import orchestrator

    seen = {}

    def fake_start(payload):
        seen["start"] = payload
        return {"status": "compliance_review"}

    def fake_decide(payload):
        seen["decision"] = payload
        return {"status": "published"}

    monkeypatch.setattr(orchestrator, "start", fake_start)
    monkeypatch.setattr(orchestrator, "decide_sync", fake_decide)

    assert agent.invoke({"type": "new_request", "request": {}})["status"] == "compliance_review"
    assert agent.invoke({"type": "decision", "run_id": "r"})["status"] == "published"
    assert set(seen) == {"start", "decision"}
