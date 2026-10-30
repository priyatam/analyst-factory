"""Spans and the newest snapshot. The exporter is in memory; nothing calls Bedrock."""
import asyncio
import json
import os

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

_EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
if not isinstance(trace.get_tracer_provider(), TracerProvider):
    trace.set_tracer_provider(_provider)


@pytest.fixture
def spans():
    _EXPORTER.clear()
    return _EXPORTER


def _state():
    return {"run_id": "run-span",
            "request": {"ticker": "AAPL", "asset_class": "equity", "analysis_type": "memo"},
            "status": "senior_review", "revision": 2, "sources": {}, "values": {},
            "risk": {"level": "low", "reasons": []}, "prior_memos": [], "gaps": [],
            "freshness": {}, "decisions": [], "memo": None, "applied": []}


def test_an_advance_span_records_the_run_the_status_and_the_revision(spans):
    from novamark.orchestrator import advance

    asyncio.run(advance(_state(), {"save": lambda state: None}))

    finished = [span for span in spans.get_finished_spans() if span.name == "advance"]
    assert len(finished) == 1
    assert finished[0].attributes["run_id"] == "run-span"
    assert finished[0].attributes["status"] == "senior_review"
    assert finished[0].attributes["revision"] == 2


def test_a_model_call_span_names_the_model_and_not_the_prompt(spans, monkeypatch):
    from novamark import model

    monkeypatch.setattr(model, "agent", lambda: (lambda prompt: "ok"))

    assert asyncio.run(model.ask("do not put this prompt on the span")) == "ok"

    finished = [span for span in spans.get_finished_spans() if span.name == "model.call"]
    assert len(finished) == 1
    assert finished[0].attributes["model_id"] == model.MODEL_ID
    assert "do not put this prompt on the span" not in finished[0].attributes.values()


def test_latest_returns_the_newer_run_when_mtimes_differ(tmp_path, monkeypatch):
    from novamark import state

    monkeypatch.setattr(state, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_BUCKET", None)
    for run_id, mtime in (("run-old", 1_700_000_000), ("run-new", 1_700_000_100)):
        folder = tmp_path / run_id
        folder.mkdir()
        path = folder / "000-published.json"
        path.write_text(json.dumps({"run_id": run_id, "status": "published"}))
        os.utime(path, (mtime, mtime))

    assert state.latest()["run_id"] == "run-new"


def test_start_does_not_build_a_provider_off_the_runtime(monkeypatch):
    from novamark import otel

    monkeypatch.delenv("STATE_BUCKET", raising=False)
    monkeypatch.delenv("AGENT_OBSERVABILITY_ENABLED", raising=False)
    monkeypatch.setattr(otel, "_started", False)

    def fail():
        raise AssertionError("ADOT initialize ran")

    import opentelemetry.instrumentation.auto_instrumentation as auto

    monkeypatch.setattr(auto, "initialize", fail)
    otel.start()
    assert os.environ.get("AGENT_OBSERVABILITY_ENABLED") is None
