"""Invoke the deployed runtime and draw the state machine as it moves.

    uv run python src/cli.py NVDA
    uv run python src/demo.py          # the clean filing, through this module

Each box is one state. It fills in when the runtime returns, because a call blocks until
the run pauses at a review or finishes. This command does not approve a review. The demo
does, either by asking or with `--auto-approve`. Every new run makes real model calls.
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
from novamark.state import MemoState, Status

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


def show_state(state: dict, console: Console | None = None) -> None:
    """Pretty-print one MemoState. Every schema field is a row."""
    console = console or Console()
    table = Table(show_header=True, header_style="bold", expand=True, show_lines=True)
    table.add_column("field", style="bold", no_wrap=True)
    table.add_column("value")
    for field in MemoState.__annotations__:
        table.add_row(field, escape(plain(state.get(field))))
    console.print(Panel(table, title="MemoState", border_style="green"))


def trace_groups(arn: str) -> list[str]:
    """Where this runtime's spans and agent logs are written."""
    runtime_id = arn.split(":runtime/", 1)[-1]
    return [f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT", "/novamark/agent", "aws/spans"]


def _attr_value(value):
    """One OpenTelemetry attribute, whether it is a bare value or a typed wrapper."""
    if isinstance(value, dict):
        for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if key in value:
                return value[key]
    return value


def _attributes(raw) -> dict:
    if isinstance(raw, dict):
        return {key: _attr_value(value) for key, value in raw.items()}
    if isinstance(raw, list):
        return {item["key"]: _attr_value(item.get("value"))
                for item in raw if isinstance(item, dict) and item.get("key")}
    return {}


def span_record(message: str) -> dict | None:
    """One CloudWatch log line as a span, or nothing if the line is not a span."""
    try:
        body = json.loads(message)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    name = body.get("name") or body.get("spanName")
    if not name:
        return None
    attrs = _attributes(body.get("attributes") or body.get("annotations") or {})
    start, end = body.get("startTimeUnixNano"), body.get("endTimeUnixNano")
    duration = ""
    start_ns = 0
    if start is not None and end is not None:
        try:
            start_ns = int(start)
            duration = f"{(int(end) - start_ns) / 1_000_000:.0f}"
        except (TypeError, ValueError):
            duration = ""
    model = attrs.get("model_id") or attrs.get("gen_ai.request.model") or ""
    resource = _attributes((body.get("resource") or {}).get("attributes") or {})
    identity = str(resource.get("cloud.resource_id") or "")
    alias = str(resource.get("service.name") or "")
    if not alias and ":runtime/" in identity:
        alias = identity.split(":runtime/", 1)[1].split("/", 1)[0]
    return {"name": str(name), "trace_id": str(body.get("traceId") or ""),
            "span_id": str(body.get("spanId") or ""), "start": start_ns,
            "identity": identity, "alias": alias,
            "status": str(attrs.get("status") or ""),
            "revision": "" if "revision" not in attrs else str(attrs.get("revision")),
            "model": str(model), "mcp": str(attrs.get("mcp.method.name") or ""),
            "http_status": str(attrs.get("http.status_code") or ""),
            "input_tokens": attrs.get("gen_ai.usage.input_tokens"),
            "output_tokens": attrs.get("gen_ai.usage.output_tokens"),
            "duration_ms": duration}


def _filter_events(client, group: str, pattern: str, start: int):
    """Pages of one CloudWatch filter. A missing or forbidden group is skipped."""
    from botocore.exceptions import ClientError

    token = None
    for _ in range(20):
        kwargs = {"logGroupName": group, "filterPattern": pattern, "startTime": start, "limit": 100}
        if token:
            kwargs["nextToken"] = token
        try:
            response = client.filter_log_events(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("ResourceNotFoundException", "AccessDeniedException"):
                return
            raise
        events = response.get("events", [])
        yield from events
        nxt = response.get("nextToken")
        if not events or not nxt or nxt == token:
            return
        token = nxt


def _unique_spans(events: list) -> list[dict]:
    """Drop a span that the run-id query and the trace-id query both returned."""
    seen = set()
    unique = []
    for event in events:
        message = event.get("message", "") if isinstance(event, dict) else ""
        record = span_record(message)
        key = record["span_id"] if record and record["span_id"] else message
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def fetch_trace(arn: str, run_id: str, client=None) -> list[dict]:
    """Every span in the traces that contain this run. The last day only.

    The run id is on the `advance` span. The actions (model calls, the market
    quote, MCP reads) are other spans in that same trace, so the second query
    is by trace id.
    """
    import time

    client = client or boto3.client("logs", region_name=REGION)
    start = int((time.time() - 24 * 3600) * 1000)
    groups = trace_groups(arn)
    found = []
    for group in groups:
        found.extend(_filter_events(client, group, f'"{run_id}"', start))
    trace_ids = []
    for event in found:
        record = span_record(event.get("message", "") if isinstance(event, dict) else "")
        if record and record["trace_id"] and record["trace_id"] not in trace_ids:
            trace_ids.append(record["trace_id"])
    for trace_id in trace_ids:
        for group in groups:
            found.extend(_filter_events(client, group, f'"{trace_id}"', start))
    return _unique_spans(found)


def _keep_span(record: dict, names: set[str]) -> bool:
    """Framework plumbing and the Strands spans that repeat a model call."""
    name = record["name"]
    if name.startswith(("fastapi.", "invoke_agent")) or name in ("execute_event_loop_cycle", "mcp.session"):
        return False
    return not (name == "model.call" and "chat" in names)


def _action(record: dict) -> str:
    if record["name"] == "advance":
        return record["status"] or "advance"
    if record["name"] in ("chat", "model.call"):
        return "model"
    if record["mcp"]:
        return f"MCP {record['mcp']}"
    return record["name"]


def _count(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tokens(record: dict) -> str:
    """Input and output tokens for one model call."""
    incoming, outgoing = _count(record["input_tokens"]), _count(record["output_tokens"])
    if incoming is None or outgoing is None:
        return ""
    return f"{incoming} in, {outgoing} out"


def _token_total(records: list[dict]) -> str:
    """Tokens across the model calls this run shows. A repeated span is not counted twice."""
    incoming = outgoing = 0
    found = False
    for record in _visible(records):
        inn, out = _count(record["input_tokens"]), _count(record["output_tokens"])
        if inn is None or out is None:
            continue
        incoming += inn
        outgoing += out
        found = True
    return f"{incoming} in, {outgoing} out" if found else ""


def _detail(record: dict) -> str:
    if record["name"] == "advance":
        return f"revision {record['revision']}" if record["revision"] != "" else ""
    parts = []
    if record["model"]:
        parts.append(record["model"])
    if record["http_status"]:
        parts.append(record["http_status"])
    return "  ".join(parts)


def _visible(records: list[dict]) -> list[dict]:
    """Spans worth a row, each process before the calls it made."""
    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(record["trace_id"], []).append(record)
    visible = []
    for group in sorted(grouped.values(), key=lambda items: min(item["start"] for item in items)):
        names = {item["name"] for item in group}
        visible.extend(sorted((item for item in group if _keep_span(item, names)),
                              key=lambda item: (item["name"] != "advance", item["start"])))
    return visible


def _action_rows(records: list[dict]) -> list[tuple[str, str, str, str, str]]:
    """One row per action, the process first and its calls indented under it."""
    rows = []
    for record in _visible(records):
        label = _action(record)
        if record["name"] != "advance":
            label = f"  {label}"
        rows.append((record["alias"], label, _detail(record), _tokens(record), record["duration_ms"]))
    return rows


def show_trace(events: list, console: Console | None = None) -> None:
    """The actions CloudWatch recorded for one run, after the line that says so."""
    console = console or Console()
    console.print("Agent trace from CloudWatch Logs: the actions recorded for this run.")
    records = []
    for event in events:
        message = event.get("message", "") if isinstance(event, dict) else ""
        record = span_record(message)
        if record:
            records.append(record)
    rows = _action_rows(records)
    if not rows:
        console.print("No spans for this run are in CloudWatch yet.")
        return
    shown = []
    for record in _visible(records):
        if record["identity"] and record["identity"] not in shown:
            shown.append(record["identity"])
            alias = f" (alias={record['alias']})" if record["alias"] else ""
            console.print(f"Identity: {record['identity']}{alias}", markup=False)
    usage = _token_total(records)
    if usage:
        console.print(f"Tokens: {usage}", markup=False)
    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("identity")
    table.add_column("action", overflow="fold")
    table.add_column("detail", overflow="fold", ratio=2)
    table.add_column("tokens", justify="right")
    table.add_column("ms", justify="right", no_wrap=True)
    for alias, action, detail, tokens, duration in rows:
        table.add_row(alias, action, detail, tokens, duration)
    console.print(table)


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
