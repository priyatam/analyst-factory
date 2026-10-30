"""The synthetic eval scores figures offline. It does not call the model."""
import pytest
from rich.console import Console

from evals import load, run, schedule


def test_the_synthetic_set_estimates_auditor_time_between_5_and_15_minutes():
    rows = load()

    assert rows
    assert {row["auditor_minutes"] for row in rows} <= set(range(5, 16))


def test_a_request_above_the_cap_runs_one_hundred():
    rows = load()

    assert len(schedule(rows, 500)) == 100
    assert len(schedule(rows, None)) == len(rows)
    with pytest.raises(ValueError):
        schedule(rows, 0)


def test_an_eval_run_calls_haiku_and_restores_sonnet(monkeypatch):
    from novamark import model, orchestrator
    from strands_evals import Case

    from evals import agent_task

    seen = {}

    async def fake_run(payload, deps):
        seen["model"] = model.MODEL_ID
        return {"values": {}}

    monkeypatch.setattr(orchestrator, "run", fake_run)
    agent_task(Case(name="helix", input="text", metadata={"ticker": "HLX"}))

    assert seen["model"] == model.EVAL_MODEL_ID
    assert model.MODEL_ID == "us.anthropic.claude-sonnet-4-6"


def test_the_report_scores_agreement_and_averages_the_auditor_estimate():
    console = Console(width=120, force_terminal=True, record=True)
    assert run(task="eval_tasks:spoil", console=console) == 1
    text = console.export_text()

    assert "consistency 67%" in text
    assert "missed" in text
    assert "average auditor review 10.0 min" in text
    assert "cap 100" in text
    for metric in ("Memo time", "Gathering", "same day", "above 90%"):
        assert metric in text
    assert "under 45 min" in text
    assert "0–15%" in text
    assert "5–15 min" in text
    assert "0%–100%" in text
