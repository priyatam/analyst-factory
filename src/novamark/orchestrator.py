"""The orchestrator: one loop over typed state.

    data_collector -> document_analyser -> senior_review?
                   -> synthesis -> compliance_review -> published

Every process has one signature, `(state, deps) -> state`, and sets the `status` of the process
that runs next. The loop is then a lookup: run the process `status` names, repeat.
`senior_review` and `compliance_review` are people: they save the state and return a packet, and
`decide` resumes the same loop from the status the decision set.
"""
import asyncio
import logging
import uuid

from . import knowledge_base, model
from .process import data_collector, document_analyser, gates, synthesize
from .state import Deps, MemoState, Process, Request, Status, load, save
from .otel import span

REQUIRED = ("ticker", "asset_class", "analysis_type")


def intake(payload: dict) -> MemoState:
    """Validate the request and create the typed state. Pure."""
    request: Request = payload["request"]
    missing = [k for k in REQUIRED if not request.get(k)]
    if missing:
        raise ValueError(f"request missing {', '.join(missing)}")
    return {"run_id": payload.get("run_id") or str(uuid.uuid4()),
            "request": {k: request[k] for k in REQUIRED}, "status": Status.DATA_COLLECTOR,
            "revision": 0, "sources": {}, "values": {}, "risk": None, "prior_memos": None,
            "gaps": [], "freshness": {}, "decisions": [], "memo": None, "applied": []}


async def run(payload: dict, deps: Deps) -> dict:
    """A new request, through the pipe until a person is needed or it publishes."""
    return await advance(intake(payload), deps)


async def decide(payload: dict, deps: Deps) -> dict:
    """Apply a review decision, then continue from the process it selects."""
    state = gates.decide(deps["load"](payload["run_id"]), payload["decision"], payload.get("roles", []))
    return await advance(state, deps)


async def advance(state: MemoState, deps: Deps) -> dict:
    """Run processes while they are ours to run; stop when the next one is a person."""
    while True:
        status = state["status"]
        with span("advance", run_id=state["run_id"], status=str(status),
                  revision=int(state["revision"])):
            logging.getLogger("novamark").info(
                "advance run_id=%s status=%s revision=%s",
                state["run_id"], status, state["revision"])
            if status in STEPS:
                state = await STEPS[status](state, deps)
            elif status in gates.REVIEWS:
                return pause(state, deps)
            else:
                return _finish(state, deps)


def _finish(state: MemoState, deps: Deps) -> dict:
    """A terminal status ends the run. `published` is already set by the approval decision."""
    final = _save(state, deps)
    return {"run_id": final["run_id"], "status": final["status"], "memo": final["memo"],
            "decisions": final["decisions"], "revision": final["revision"]}


async def gather(state: MemoState, deps: Deps) -> MemoState:
    """The two independent sources at once, then the analyser, which needs both."""
    branches = await asyncio.gather(
        data_collector.collect(state, deps), knowledge_base.prior_research(state, deps))
    return merge(state, *branches)


# The process each non-human status runs. All share one signature.
STEPS: dict[Status, Process] = {Status.DATA_COLLECTOR: gather,
                                 Status.DOCUMENT_ANALYSER: document_analyser.analyse,
                                 Status.SYNTHESIS: synthesize.synthesize}


def _save(state: MemoState, deps: Deps) -> MemoState:
    """Append one snapshot. The store assigns the sequence, so the state is unchanged."""
    deps["save"](state)
    return state


def pause(state: MemoState, deps: Deps) -> dict:
    """A review is the next process: save and return the packet, hold nothing open."""
    return gates.packet(_save(state, deps), state["status"])


def merge(base: MemoState, *branches: MemoState) -> MemoState:
    """Join concurrent branches, each a full state derived from `base`.

    A key takes the value of the branch that changed it. Gaps append, so no branch's gap is lost.
    """
    changed = {k: v for b in branches for k, v in b.items() if k != "gaps" and v != base[k]}
    gaps = [*base["gaps"], *(g for b in branches for g in b["gaps"][len(base["gaps"]):])]
    return {**base, **changed, "gaps": gaps}


def start(payload: dict) -> dict:
    """The sync door the runtime uses."""
    return asyncio.run(run(payload, _deps()))


def decide_sync(payload: dict) -> dict:
    return asyncio.run(decide(payload, _deps()))


def _deps() -> Deps:
    return {"ask": model.ask, "quote": data_collector.quote(), "filings": data_collector.filings,
            "kb": knowledge_base.history, "save": save, "load": load}
