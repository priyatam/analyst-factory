"""Invoke the deployed runtime and draw the state machine as it moves.

    uv run python src/cli.py NVDA
    uv run python src/demo.py          # both tickers, through this module

Each box is one state. It fills in when the runtime returns, because a call blocks until
the run pauses at a review or finishes. This command does not approve a review. The demo
does, either by asking or with `--auto`. Every new run makes real model calls.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.columns import Columns
from rich.live import Live
from rich.markdown import Markdown

from novamark.model import REGION
from novamark.state import Status

ORDER = (
    Status.DATA_COLLECTOR, Status.DOCUMENT_ANALYSER, Status.SENIOR_REVIEW,
    Status.SYNTHESIS, Status.COMPLIANCE_REVIEW, Status.PUBLISHED,
)
BEFORE = {
    Status.SENIOR_REVIEW: (Status.DATA_COLLECTOR, Status.DOCUMENT_ANALYSER),
    Status.COMPLIANCE_REVIEW: (Status.DATA_COLLECTOR, Status.DOCUMENT_ANALYSER, Status.SYNTHESIS),
}
COLOR = {
    Status.DATA_COLLECTOR: "cyan",
    Status.DOCUMENT_ANALYSER: "cyan",
    Status.SENIOR_REVIEW: "yellow",
    Status.SYNTHESIS: "magenta",
    Status.COMPLIANCE_REVIEW: "blue",
    Status.PUBLISHED: "green",
    Status.ESCALATED: "red",
}
ROLES = {Status.SENIOR_REVIEW: "senior_analyst", Status.COMPLIANCE_REVIEW: "compliance_officer"}


def require_arn() -> str:
    """The runtime ARN from the environment, or an error the caller can print."""
    arn = os.getenv("NOVAMARK_RUNTIME_ARN")
    if not arn:
        raise SystemExit("set NOVAMARK_RUNTIME_ARN to the deployed runtime")
    if ":runtime/" not in arn:
        raise SystemExit(f"not an AgentCore runtime ARN (arn:aws:bedrock-agentcore:...:runtime/...): {arn}")
    return arn


def invoke(arn: str, payload: dict) -> dict:
    """POST one payload to the runtime. The ARN goes in the URL encoded."""
    url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{urllib.parse.quote(arn, safe='')}/invocations"
    body = json.dumps(payload)
    signed = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "bedrock-agentcore", REGION).add_auth(signed)
    req = urllib.request.Request(url, data=body.encode(), headers=dict(signed.headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:500]}") from None


def send_decision(arn: str, packet: dict, decision: dict) -> dict:
    """Send one reviewer decision. `decision` has action, reviewer, and comment."""
    gate = packet["gate"]
    return invoke(arn, {"type": "decision", "run_id": packet["run_id"], "roles": [ROLES[gate]],
                        "decision": {"gate": gate, "action": decision["action"],
                                     "reviewer": decision["reviewer"],
                                     "comment": decision.get("comment", ""),
                                     "id": str(uuid.uuid4())}})


def blank(ticker: str, label: str) -> dict:
    return {"ticker": ticker, "label": label, "done": set(), "skipped": set(),
            "rejected": set(), "current": None, "waiting": "calling the runtime", "step": None}


def observe(view: dict, step: dict) -> None:
    """Record the state the runtime just reported. Earlier states are done or skipped."""
    view["step"] = step
    view["waiting"] = ""
    gate = step.get("gate")
    if gate in BEFORE:
        view["done"].update(BEFORE[gate])
        visited = view["current"] == Status.SENIOR_REVIEW or Status.SENIOR_REVIEW in view["done"]
        if gate == Status.COMPLIANCE_REVIEW and not visited:
            view["skipped"].add(Status.SENIOR_REVIEW)
        if view["current"]:
            view["done"].add(view["current"])
        view["current"] = gate
        return
    status = step.get("status")
    if view["current"]:
        view["done"].add(view["current"])
    view["done"].update(s for s in ORDER if s != status and s not in view["skipped"])
    view["current"] = status


def _box(name: str, kind: str) -> Panel:
    color = "red" if kind == "rejected" else COLOR.get(name, "white")
    if kind in ("current", "rejected"):
        return Panel(f"[bold]{name}[/]", border_style=color, style=color)
    if kind == "done":
        return Panel(name, border_style="green")
    if kind == "skipped":
        return Panel(f"[dim]{name}\nskipped[/]", border_style="grey50")
    return Panel(f"[dim]{name}[/]", border_style="grey37")


def track(view: dict) -> Panel:
    """One box per state, colored by whether the run has reached it."""
    boxes = []
    for name in ORDER:
        if name in view["rejected"]:
            kind = "rejected"
        elif name == view["current"]:
            kind = "current"
        elif name in view["done"]:
            kind = "done"
        elif name in view["skipped"]:
            kind = "skipped"
        else:
            kind = "pending"
        boxes.append(_box(name, kind))
    return Panel(Columns(boxes, equal=True, expand=True),
                 title=f"{view['label']}: {view['ticker']}", border_style="white")


def plain(value) -> str:
    """A figure as a customer would read it, with no JSON punctuation."""
    if isinstance(value, str) and value.strip()[:1] in "{[":
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    if value is None or value == "":
        return "not stated"
    if isinstance(value, dict):
        return "\n".join(f"{key}: {plain(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "\n".join(plain(item) for item in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _values(step: dict) -> Table:
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("metric")
    table.add_column("value")
    table.add_column("confidence", justify="right")
    table.add_column("excerpt")
    flagged = set(step.get("flagged") or [])
    for name, entry in (step.get("values") or {}).items():
        style = "yellow" if name in flagged else ""
        value = escape(plain(entry.get("value")))
        table.add_row(name, value, escape(str(entry.get("confidence"))),
                      escape(entry.get("excerpt") or ""), style=style)
    return table


def body(view: dict):
    """The review the run is waiting on, the memo, or a wait line."""
    step = view["step"]
    if view["waiting"] and not step:
        return Spinner("dots", text=view["waiting"])
    if not step:
        return ""
    if step.get("status") in (Status.PUBLISHED, Status.ESCALATED):
        color = COLOR.get(step["status"], "white")
        memo = step.get("memo") or "(no memo)"
        title = f"{step['status']}  ·  {len(step.get('decisions') or [])} decisions"
        return Panel(Markdown(memo), title=title, border_style=color)
    risk = step.get("risk") or {}
    gaps = [g.get("source") for g in step.get("gaps") or []]
    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold")
    head.add_column()
    head.add_row("role", escape(str(step.get("role"))))
    head.add_row("flagged", escape(", ".join(step.get("flagged") or [])) or "none")
    head.add_row("risk", escape(f"{risk.get('level')}  {'; '.join(risk.get('reasons') or [])}"))
    head.add_row("gaps", escape(", ".join(gaps)) or "none")
    color = COLOR.get(step.get("gate"), "white")
    panel = Panel(Group(head, _values(step)), title=str(step.get("gate")), border_style=color)
    if view["waiting"]:
        return Group(panel, Spinner("dots", text=view["waiting"]))
    return panel


def screen(view: dict) -> Group:
    return Group(track(view), body(view))


def run(arn: str, ticker: str, label: str, *, decide=None, console: Console | None = None) -> int:
    """One ticker. `decide(packet, console)` answers a review. Without it, the run stops at the gate."""
    console = console or Console()
    err = Console(stderr=True)
    view = blank(ticker, label)
    try:
        with Live(screen(view), console=console, refresh_per_second=8) as live:
            step = invoke(arn, {"type": "new_request", "request": {
                "ticker": ticker, "asset_class": "equity", "analysis_type": "memo"}})
            while True:
                observe(view, step)
                live.update(screen(view))
                if not step.get("gate"):
                    break
                if decide is None:
                    break
                live.stop()
                decision = decide(step, console)
                if decision["action"] == "reject":
                    view["rejected"].add(step["gate"])
                else:
                    view["rejected"].discard(step["gate"])
                view["waiting"] = f"sending {decision['action']} from {decision['reviewer']}"
                live.start()
                live.update(screen(view))
                step = send_decision(arn, step, decision)
    except (RuntimeError, urllib.error.URLError, KeyError) as exc:
        err.print(f"error: {exc}", style="bold red", markup=False)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """One ticker. The demo calls `run` for both."""
    import argparse

    parser = argparse.ArgumentParser(description="Run one memo on the deployed runtime")
    parser.add_argument("ticker", help="AAPL, NVDA, or MSFT")
    parser.add_argument("--label", default="run")
    args = parser.parse_args(argv)
    try:
        arn = require_arn()
    except SystemExit as exc:
        Console(stderr=True).print(str(exc), style="bold red")
        return 1
    return run(arn, args.ticker.upper(), args.label)


if __name__ == "__main__":
    sys.exit(main())
