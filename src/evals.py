"""Score the agent on the synthetic filings. At most 100 runs.

The demo writes an experiment file, then:

    strands-evals validate <file> --custom-evaluator evals:Figures
    strands-evals run <file> --task evals:agent_task --custom-evaluator evals:Figures --fail-on threshold:0.9

`threshold:0.9` is the consistency target: the command exits 1 when the mean score is under 90%.
Auditor minutes are the 5–15 estimate on each case. The agent time is the clock on that run.

    uv run python src/demo.py --run-evals
    uv run python src/demo.py --run-evals --runs 100
"""
import asyncio
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table
from strands_evals import Case, Experiment
from strands_evals.evaluators import Evaluator
from strands_evals.types.evaluation import EvaluationData, EvaluationOutput
from strands_evals.types.evaluation_report import EvaluationReport

from novamark.model import DATA_DIR

MAX_RUNS = 100
FAIL_ON = "threshold:0.9"
EVALUATOR = "evals:Figures"


def load() -> list[dict]:
    """The labelled synthetic cases. Each auditor estimate is between 5 and 15 minutes."""
    rows = json.loads((DATA_DIR / "synthetic" / "cases.json").read_text())
    for row in rows:
        minutes = row["auditor_minutes"]
        if not 5 <= minutes <= 15:
            raise ValueError(f"{row['name']} auditor_minutes must be from 5 to 15")
    return rows


def schedule(cases: list[dict], runs: int | None) -> list[dict]:
    """One row per run, cycling the cases. Never more than 100."""
    if not cases:
        raise ValueError("no synthetic cases")
    count = len(cases) if runs is None else runs
    if count < 1:
        raise ValueError("runs must be at least 1")
    count = min(count, MAX_RUNS)
    return [{**cases[i % len(cases)], "name": f"{cases[i % len(cases)]['name']} #{i + 1}"}
            for i in range(count)]


def _same(got, want) -> bool:
    try:
        return abs(float(got) - float(want)) < 1e-6
    except (TypeError, ValueError):
        return got == want


class Figures(Evaluator):
    """Share of expected figures present with the labelled value. No model judge."""

    def evaluate(self, evaluation_case: EvaluationData) -> list[EvaluationOutput]:
        expected = evaluation_case.expected_output or {}
        actual = evaluation_case.actual_output or {}
        misses = [key for key, want in expected.items() if not _same(actual.get(key), want)]
        score = (len(expected) - len(misses)) / len(expected) if expected else 0.0
        reason = "figures match" if not misses else "missed " + ", ".join(misses)
        return [EvaluationOutput(score=score, test_pass=score == 1.0, reason=reason)]


def agent_task(case: Case) -> dict:
    """One local memo, stopped at the first review. The model is Haiku."""
    from novamark import model, orchestrator
    from novamark import state as store

    started = time.perf_counter()
    previous = model.MODEL_ID
    model.MODEL_ID = model.EVAL_MODEL_ID
    try:
        text = case.input
        ticker = case.metadata["ticker"]

        def filings(_ticker: str) -> dict:
            return {"DOC-SYN": {"text": text, "filing_date": "2026-01-15", "doc_id": "DOC-SYN"}}

        async def quote(_ticker: str) -> dict:
            return {"as_of": "2026-01-15T00:00:00Z", "source": "synthetic", "data": {"price": 20.0}}

        async def kb(_ticker: str) -> list:
            return []

        packet = asyncio.run(orchestrator.run(
            {"request": {"ticker": ticker, "asset_class": "equity", "analysis_type": "memo"}},
            {"ask": model.ask, "quote": quote, "filings": filings, "kb": kb,
             "save": store.save, "load": store.load}))
        figures = {key: value["value"] for key, value in packet["values"].items()}
        return {"output": figures}
    finally:
        model.MODEL_ID = previous
        _note(case.name, time.perf_counter() - started)


def _case(row: dict) -> Case:
    return Case(name=row["name"], session_id=row["name"], input=row["filing"],
                expected_output=row["expected"],
                metadata={"ticker": row["ticker"], "auditor_minutes": row["auditor_minutes"]})


def write_experiment(rows: list[dict], path: Path) -> None:
    """Serialize the cases and the Figures evaluator for `strands-evals validate`."""
    Experiment(cases=[_case(row) for row in rows], evaluators=[Figures()]).to_file(str(path))


def labelled_task(case: Case) -> dict:
    """The labelled figures. Used to check the CLI without calling the model."""
    return {"output": dict(case.expected_output)}


def _note(name: str | None, seconds: float) -> None:
    path = os.environ.get("NOVAMARK_EVAL_TIMINGS")
    if not path or not name:
        return
    file = Path(path)
    data = json.loads(file.read_text()) if file.exists() else {}
    data[name] = seconds
    file.write_text(json.dumps(data))


def _seconds(rows: list[dict], path: Path) -> list[float]:
    data = json.loads(path.read_text()) if path.exists() else {}
    return [float(data.get(row["name"], 0.0)) for row in rows]


def _strands(args: list[str], timings: Path) -> int:
    """One strands-evals command. `src` is on the path so `evals:Figures` imports."""
    src = str(DATA_DIR.parent)
    root = str(DATA_DIR.parent.parent)
    tests = str(Path(root) / "tests")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(p for p in (src, tests, root, env.get("PYTHONPATH", "")) if p)
    env["NOVAMARK_EVAL_TIMINGS"] = str(timings)
    return subprocess.run(["strands-evals", *args], env=env).returncode


def projections(report, rows: list[dict], seconds: list[float]) -> list[tuple[str, str, str, str, str]]:
    """Today, the target, the baseline from this run, and the range around it. One row per success metric."""
    agent = sum(seconds) / len(seconds)
    auditor = sum(row["auditor_minutes"] for row in rows) / len(rows)
    memo = agent / 60 + auditor
    low, high = min(seconds) / 60 + 5, max(seconds) / 60 + 15
    errors = sum(1 for reason in report.reasons if reason and reason.startswith("An error occurred"))
    covered = "complete for these runs" if errors == 0 else f"{len(rows) - errors} of {len(rows)} runs"
    scores = report.scores or [0.0]
    return [
        ("1 Memo time", "4–6 hours", "under 45 min", f"{memo:.0f} min", f"{low:.0f}–{high:.0f} min"),
        ("2 Gathering", "about 65%", "under 20%", "about 0%", "0–15%"),
        ("3 Compliance cycle", "2–3 days", "same day", f"{auditor:.0f} min", "5–15 min"),
        ("4 Audit coverage", "none", "complete", covered, "these runs to every published memo"),
        ("5 Consistency", "58%", "above 90%", f"{report.overall_score:.0%}",
         f"{min(scores):.0%}–{max(scores):.0%}"),
    ]


def show(report, rows: list[dict], seconds: list[float], console: Console | None = None) -> None:
    """Per-run scores, then a guesstimate and a projected range for the five success metrics."""
    console = console or Console()
    console.print(
        "Synthetic eval. Consistency is labelled-figure agreement. "
        "Auditor minutes are a 5–15 estimate, not a measured wait. "
        "The ranges below are a projection from this run.")
    table = Table(show_header=True, header_style="bold")
    table.add_column("case")
    table.add_column("score", justify="right")
    table.add_column("agent s", justify="right")
    table.add_column("auditor min", justify="right")
    table.add_column("notes")
    for i, row in enumerate(rows):
        table.add_row(row["name"], f"{report.scores[i]:.2f}", f"{seconds[i]:.1f}",
                      str(row["auditor_minutes"]), report.reasons[i] or "")
    console.print(table)
    minutes = [row["auditor_minutes"] for row in rows]
    console.print(f"runs {len(rows)} (cap {MAX_RUNS})")
    console.print(f"consistency {report.overall_score:.0%}")
    console.print(f"average agent time {sum(seconds) / len(seconds):.1f}s")
    console.print(f"average auditor review {sum(minutes) / len(minutes):.1f} min (estimate)")
    metrics = Table(show_header=True, header_style="bold", title="Success metrics")
    for heading in ("metric", "today", "target", "baseline", "range"):
        metrics.add_column(heading)
    for row in projections(report, rows, seconds):
        metrics.add_row(*row)
    console.print(metrics)


def run(runs: int | None = None, task: str = "evals:agent_task", console: Console | None = None) -> int:
    """Validate the experiment, run it, print the report. Exit 1 when consistency is under 90%."""
    rows = schedule(load(), runs)
    directory = Path(tempfile.mkdtemp(prefix="novamark-eval-"))
    experiment = directory / "experiment.json"
    report_path = directory / "report.json"
    timings = directory / "timings.json"
    write_experiment(rows, experiment)
    if _strands(["validate", str(experiment), "--custom-evaluator", EVALUATOR], timings):
        return 2
    code = _strands(["run", str(experiment), "--task", task, "--custom-evaluator", EVALUATOR,
                     "--fail-on", FAIL_ON, "-o", str(report_path)], timings)
    if report_path.exists():
        report = EvaluationReport.model_validate_json(report_path.read_text())
        show(report, rows, _seconds(rows, timings), console)
    return code
