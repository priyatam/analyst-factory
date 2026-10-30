"""Fixtures for the edges. No network, no model, no clock."""
import pytest

from novamark import state as store
from tests.support import Model


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """Fail the run if any test reaches Bedrock, Anthropic, or a socket.

    Opt out with `@pytest.mark.allow_network` for the tests that exist to call a deployment.
    """
    if request.node.get_closest_marker("allow_network"):
        return
    import socket

    import botocore.endpoint

    def blocked(*a, **k):
        raise RuntimeError("test reached the network; inject the edge instead")

    monkeypatch.setattr(botocore.endpoint.Endpoint, "_send", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture
def deps(tmp_path, monkeypatch):
    """Real filings and store, fake model and market. One factory per test."""
    monkeypatch.setattr(store, "STATE_DIR", tmp_path)
    from novamark.process import data_collector

    def make(model: Model, quote=None, kb=None) -> dict:
        async def market(ticker):
            if callable(quote):
                return await quote(ticker)
            return quote or {"as_of": "2026-10-29T00:00:00Z", "source": "fake",
                             "data": {"pe_ratio": 52.7}}

        async def prior(ticker):
            if kb is not None:
                return await kb(ticker) if callable(kb) else kb
            return [{"date": "2026-01-30", "recommendation": "Buy"}]

        return {"ask": model, "quote": market, "filings": data_collector.filings,
                "kb": prior, "save": store.save, "load": store.load}

    return make
