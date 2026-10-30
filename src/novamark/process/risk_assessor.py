"""Risk assessor, nested inside the analyser. Own prompt, own structured output.

The model supplies reasons; the level comes from `model.RISK_THRESHOLDS`. Compliance can
retune the rule without touching a prompt.
"""
import json

from .. import model
from ..state import MemoState, Risk

PROMPT = """List the concrete risks stated in this text, one short sentence each, as JSON only:
{{"reasons": ["..."]}}

Text:
{text}
"""

# Customer concentration and export controls. A supplier "concentrated with" does not match.
SEVERE = ("concentrated among", "export control")


def parse(text: str) -> list[str]:
    start, end = text.find("{"), text.rfind("}")
    return list(json.loads(text[start:end + 1]).get("reasons", []))


def level(reasons: list[str], values: dict) -> Risk:
    """High on a stated concentration or export-control risk, or two or more weak values."""
    weak = [k for k, f in values.items()
            if (f["confidence"] or 0) < model.RISK_THRESHOLDS["confidence"]]
    if any(s in r.lower() for r in reasons for s in SEVERE) or len(weak) >= 2:
        return Risk(level="high", reasons=reasons)
    return Risk(level="medium" if reasons or weak else "low", reasons=reasons)


async def assess(state: MemoState, deps) -> MemoState:
    """One model call for the reasons; the level is computed from them and the values."""
    reasons = parse(await deps["ask"](PROMPT.format(text="\n\n".join(state["sources"].values()))))
    return {**state, "risk": level(reasons, state["values"])}
