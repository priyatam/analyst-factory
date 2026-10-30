"""The two reviews: a senior analyst before the memo, a compliance officer before publish.

A gate is saved state plus a later call, not a held connection. The reviewer's action sets the
process that runs next, so `status` is always a process from the data flow.
"""
from .. import model
from ..state import Decision, MemoState, Status

# The status a review is reached from, and the role allowed to clear it.
ROLE = {Status.SENIOR_REVIEW: "senior_analyst", Status.COMPLIANCE_REVIEW: "compliance_officer"}

# Where an approval sends the run, and where a rejection sends it back to.
NEXT = {Status.SENIOR_REVIEW: Status.SYNTHESIS, Status.COMPLIANCE_REVIEW: Status.PUBLISHED}
BACK = {Status.SENIOR_REVIEW: Status.DOCUMENT_ANALYSER, Status.COMPLIANCE_REVIEW: Status.SYNTHESIS}

REVIEWS = tuple(ROLE)


def needs_gate1(state: MemoState) -> bool:
    """Any value under the floor, or high risk, goes to a senior analyst."""
    low = any((v["confidence"] or 0) < model.CONFIDENCE_FLOOR for v in state["values"].values())
    return low or (state["risk"] or {}).get("level") == "high"


def flagged(state: MemoState) -> list[str]:
    """The values that caused the pause, so the reviewer sees why."""
    return [k for k, v in state["values"].items()
            if (v["confidence"] or 0) < model.CONFIDENCE_FLOOR]


def packet(state: MemoState, status: str) -> dict:
    """What the reviewer sees: context, the reasoning, and what is missing."""
    return {"run_id": state["run_id"], "gate": status, "role": ROLE[status],
            "revision": state["revision"],
            "reason": "confidence below floor or high risk"
                      if status == Status.SENIOR_REVIEW else "compliance sign-off",
            "flagged": flagged(state) if status == Status.SENIOR_REVIEW else [],
            "values": state["values"], "risk": state["risk"],
            "prior_memos": state["prior_memos"], "gaps": state["gaps"], "memo": state["memo"]}


def can_decide(roles: list[str], status: str) -> bool:
    return ROLE[status] in roles


def decide(state: MemoState, decision: dict, roles: list[str]) -> MemoState:
    """Record the decision, once.

    A retried call is a no-op: the decision carries an id and the state keeps the ids it has
    applied, so the transition is idempotent without a lock. Without an id every call is a new
    decision, which is what a fresh reviewer action is.
    """
    gate = decision["gate"]
    if gate not in ROLE:
        raise ValueError(f"unknown gate {gate!r}; expected one of {REVIEWS}")
    if not can_decide(roles, gate):
        raise PermissionError(f"{ROLE[gate]} required for {gate}")

    key = decision.get("id")
    if key and key in state["applied"]:
        return state

    action = decision["action"]
    values = {**state["values"], **_stamp(decision.get("amended_values") or {})}
    decisions = [*state["decisions"], Decision(
        gate=gate, action=action, reviewer=decision["reviewer"],
        comment=decision.get("comment", ""), decided_at=model.now(), id=key or "")]
    applied = [*state["applied"], key] if key else state["applied"]

    if action in ("approve", "amend"):
        return {**state, "decisions": decisions, "values": values, "applied": applied,
                "status": NEXT[gate]}

    revision = state["revision"] + 1
    return {**state, "decisions": decisions, "values": values, "applied": applied,
            "revision": revision,
            "status": Status.ESCALATED if revision >= model.MAX_REVISIONS else BACK[gate]}


def _stamp(amended: dict) -> dict:
    """A human value carries its own evidence: the reviewer, full confidence, no model."""
    return {k: {**v, "model_id": "human_amend", "confidence": 1.0, "produced_at": model.now(),
                "step": "human_amend"} for k, v in amended.items()}
