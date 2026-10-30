"""Pass each AI value on only with a citation and a confidence.

`state["values"]` is a dict of metric name to dict. This is the only place that decides
whether a value may continue, and it is deliberately a plain loop: both a citation and a
confidence are required, and the citation must occur in the source it names.
"""
from ..state import MemoState


class EvidenceError(ValueError):
    """A value without a citation, without a confidence, or citing text it did not come from."""


def squash(text: str) -> str:
    return " ".join(text.split())


def evidence_check(state: MemoState) -> MemoState:
    for name, f in state["values"].items():
        if f["value"] is None:  # not stated in the sources: nothing to cite, gate 1 flags it
            continue
        if not f["excerpt"] or f["confidence"] is None:
            raise EvidenceError(f"{name}: needs both a citation and a confidence")
        source = squash(state["sources"].get(f["source_id"], ""))
        if squash(f["excerpt"]) not in source:
            raise EvidenceError(f"{name}: excerpt not found in source {f['source_id']}")
    return state
