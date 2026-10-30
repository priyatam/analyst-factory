"""Synthesize writes the memo from approved values only."""
from .. import model
from ..state import MemoState, Status

PROMPT = """Write a one-page investment memo for {ticker} from these approved values only.

Cite each figure as [source_id]. Where a value is null or its confidence is below {floor},
write "not disclosed" and say what is missing. Where a gap is listed, write "no prior
research available". Do not add figures of your own. If reviewer comments are given, address
each one.

Values:
{values}

Risk: {risk}
Prior research: {prior}
Gaps: {gaps}
Reviewer comments: {comments}
"""


def comments(state: MemoState) -> list[str]:
    return [d["comment"] for d in state["decisions"] if d["action"] != "approve" and d["comment"]]


def prompt(state: MemoState) -> str:
    """The prompt body, so what the memo is written from is testable."""
    return PROMPT.format(ticker=state["request"]["ticker"], floor=model.CONFIDENCE_FLOOR,
                         values=state["values"], risk=state["risk"], prior=state["prior_memos"],
                         gaps=state["gaps"], comments=comments(state))


async def synthesize(state: MemoState, deps) -> MemoState:
    """Approved values in, memo out. A rejection re-enters here with its comment."""
    return {**state, "memo": await deps["ask"](prompt(state)), "status": Status.COMPLIANCE_REVIEW}
