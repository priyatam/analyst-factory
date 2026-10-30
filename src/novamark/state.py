"""The state machine's data: one `MemoState` per run, how processes use it, where it is stored.

A run is a single `MemoState` dict. `status` names the process that runs next, so the dict is
both the data and the machine's position. Three rules keep it a state machine:

1. One signature. Every process is `(state, deps) -> state` (`Process` below).
2. Immutable steps. A process never edits the dict it receives. It returns
   `{**state, <what it produced>, "status": <next process>}`.
3. Transitions are saved, not held. At a human review or the end, the orchestrator appends the
   whole state as a snapshot; a later call loads the latest one and re-enters the loop.

Who writes what (every other key passes through unchanged):

    process                         writes
    ------------------------------  ---------------------------------------------------
    orchestrator.intake             run_id, request, and the empty start of everything
    data_collector.collect          sources, freshness, gaps            -> document_analyser
    knowledge_base.prior_research   prior_memos, gaps  (beside collect; status untouched)
    document_analyser.analyse       values, risk                        -> senior_review
      (calls risk_assessor.assess      reads sources                      or synthesis
       and evidence_check, which                                          (needs_gate1)
       only read or raise)
    gates.decide                    decisions, applied, values, revision -> NEXT or BACK
                                    (a person's action, not a model's)    or escalated
    synthesize.synthesize           memo; reads values, risk, prior_memos, gaps, decisions
                                                                         -> compliance_review

Processes read the keys they need and nothing else is shared: no globals, no side channel. The
two human statuses are not processes; the orchestrator saves and returns `gates.packet`.
"""
import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Awaitable, Callable, Literal, TypedDict

from .model import REGION

STATE_DIR = Path(os.getenv("STATE_DIR", ".state"))
STATE_BUCKET = os.getenv("STATE_BUCKET")  # set on AWS: state outlives the runtime session


class Risk(TypedDict):
    level: Literal["low", "medium", "high"]
    reasons: list[str]


class Gap(TypedDict):
    source: str
    reason: str


class Decision(TypedDict):
    gate: Literal["senior_review", "compliance_review"]
    action: Literal["approve", "reject", "amend"]
    reviewer: str
    comment: str
    decided_at: str
    id: str  # the caller's decision id, so a retry is not applied twice


class Request(TypedDict):
    ticker: str
    asset_class: str
    analysis_type: str


class Status(StrEnum):
    """The states of the machine. `MemoState.status` is one of these.

    Each names the process that runs next. The members are strings, so a saved snapshot reads
    `"status": "senior_review"` and compares equal to that string after a reload.
    """
    DATA_COLLECTOR = "data_collector"
    DOCUMENT_ANALYSER = "document_analyser"
    SENIOR_REVIEW = "senior_review"          # waits for a senior analyst
    SYNTHESIS = "synthesis"
    COMPLIANCE_REVIEW = "compliance_review"  # waits for a compliance officer
    PUBLISHED = "published"                  # terminal
    ESCALATED = "escalated"                  # terminal: three rejections


class MemoState(TypedDict):
    """The run: passed to every process, returned by every process, saved as each snapshot."""
    run_id: str
    request: Request
    status: Status                   # the process that runs next
    revision: int
    sources: dict[str, str]          # source id -> exact text, so a citation can be checked
    values: dict[str, dict]          # metric name -> {value, excerpt, confidence, ...}
    risk: Risk | None
    prior_memos: list[dict] | None
    gaps: list[Gap]
    freshness: dict[str, str]        # when each source was last current
    decisions: list[Decision]
    memo: str | None
    applied: list[str]  # decision ids already folded in, so a retried call is a no-op


class Deps(TypedDict):
    """Every edge. Tests pass fakes; `agent.py` passes the real ones."""
    ask: Callable[[str], Awaitable[str]]                    # prompt -> model text
    quote: Callable[[str], Awaitable[dict]]                 # ticker -> market payload
    filings: Callable[[str], dict[str, dict]]               # ticker -> {doc_id: {...}}
    kb: Callable[[str], Awaitable[list[dict]]]              # ticker -> prior memos
    save: Callable[[MemoState], None]
    load: Callable[[str], MemoState]


# What every automatic step is: state in, new state out, `status` set to what runs next.
Process = Callable[[MemoState, Deps], Awaitable[MemoState]]


# --- the store ------------------------------------------------------------------------------


def _snapshot_key(run_id: str, seq: int, status: str) -> str:
    """One key per transition. Lexical order is chronological order, so the list is the log."""
    return f"runs/{run_id}/{seq:03d}-{status}.json"


def save(state: MemoState) -> None:
    """Append one immutable snapshot per transition. Never overwrite an existing key."""
    body = json.dumps(state, indent=2).encode()
    if STATE_BUCKET:
        import boto3

        s3 = boto3.client("s3", region_name=REGION)
        prefix = f"runs/{state['run_id']}/"
        existing = s3.list_objects_v2(Bucket=STATE_BUCKET, Prefix=prefix).get("Contents", [])
        s3.put_object(Bucket=STATE_BUCKET,
                      Key=_snapshot_key(state["run_id"], len(existing), state["status"]),
                      Body=body, IfNoneMatch="*")  # a duplicate sequence is an error, not an update
        return

    folder = Path(STATE_DIR) / state["run_id"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _snapshot_key(state["run_id"], len(list(folder.glob("*.json"))),
                                  state["status"]).split("/")[-1]
    if path.exists():
        raise FileExistsError(f"snapshot already written: {path}")
    path.write_bytes(body)


def snapshots(run_id: str) -> list[str]:
    """The run's keys in order. The list is the transition log, oldest first."""
    if STATE_BUCKET:
        import boto3

        s3 = boto3.client("s3", region_name=REGION)
        keys = [o["Key"] for o in s3.list_objects_v2(
            Bucket=STATE_BUCKET, Prefix=f"runs/{run_id}/").get("Contents", [])]
        return sorted(k.split("/")[-1] for k in keys)
    return sorted(p.name for p in (Path(STATE_DIR) / run_id).glob("*.json"))


def latest() -> MemoState:
    """The newest snapshot of the newest run.

    Locally that is the file with the newest mtime under STATE_DIR. On S3 it is
    the object under runs/ with the newest LastModified, and load reads that run.
    """
    if STATE_BUCKET:
        import boto3

        s3 = boto3.client("s3", region_name=REGION)
        newest_at = None
        run_id = None
        pages = s3.get_paginator("list_objects_v2").paginate(Bucket=STATE_BUCKET, Prefix="runs/")
        for page in pages:
            for obj in page.get("Contents", []):
                parts = obj["Key"].split("/")
                if len(parts) < 3 or not parts[1]:
                    continue
                modified = obj["LastModified"]
                if newest_at is None or modified > newest_at:
                    newest_at = modified
                    run_id = parts[1]
        if run_id is None:
            raise FileNotFoundError("no snapshots")
        return load(run_id)

    files = list(Path(STATE_DIR).glob("*/*.json"))
    if not files:
        raise FileNotFoundError("no snapshots")
    newest = max(files, key=lambda path: path.stat().st_mtime)
    return load(newest.parent.name)


def load(run_id: str) -> MemoState:
    """The latest snapshot, which is the run's current state."""
    if STATE_BUCKET:
        import boto3

        s3 = boto3.client("s3", region_name=REGION)
        keys = [o["Key"] for o in s3.list_objects_v2(
            Bucket=STATE_BUCKET, Prefix=f"runs/{run_id}/").get("Contents", [])]
        if not keys:
            raise FileNotFoundError(f"no snapshots for run {run_id}")
        return json.loads(s3.get_object(Bucket=STATE_BUCKET, Key=max(keys))["Body"].read())

    found = list((Path(STATE_DIR) / run_id).glob("*.json"))
    if not found:
        raise FileNotFoundError(f"no snapshots for run {run_id}")
    return json.loads(max(found, key=lambda p: p.name).read_text())
