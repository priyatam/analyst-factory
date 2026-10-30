"""Document analyser: metrics against a schema, each with a citation and a confidence.

The model proposes; this module decides. Confidence is capped when a figure carries no scale
(`$11,900` beside `$115.2 billion`), because a model will otherwise report the garbled cell
like any other number. Risk is assessed here, nested, on the extracted values.
"""
import json
import re

from .. import model
from . import risk_assessor
from .evidence_check import evidence_check
from .gates import needs_gate1
from ..state import MemoState, Status

SCHEMA = ("revenue", "gross_margin", "operating_income", "net_sales", "cloud_revenue",
          "segment_revenue", "capex_outlook", "copilot_contribution")

PROMPT = """Extract these metrics from the text: {schema}.

Return JSON only:
{{"values": {{"<metric>": {{"value": <number|string|null>, "excerpt": "<exact sentence>",
"confidence": <0..1>, "reason": "<one sentence>", "source_id": "<doc id>"}}}}}}

Rules: copy the excerpt exactly. Include a metric only when the text states a figure
for it, or explicitly declines to quantify it. If the text never mentions the metric,
omit the key. A decline is a null value, the sentence that declines, confidence below
0.5, and a reason that says so. If units conflict, keep the figure and lower the
confidence.

Text:
{text}
"""

AMOUNT = re.compile(r"\$(\d[\d,]*(?:\.\d+)?)\s*([A-Za-z]+)?")
SCALES = {"billion", "million", "thousand", "bn", "mm", "m"}
CAP = 0.5  # confidence ceiling for a figure that has no scale word
DECLINED = ("not break", "declin", "not disclosed", "will not", "no guidance")


def unscaled(excerpt: str) -> bool:
    """True when an amount carries no scale word, so it cannot be compared to the others."""
    return any((m.group(2) or "").lower() not in SCALES for m in AMOUNT.finditer(excerpt))


def parse(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])["values"]


def declined(raw: dict) -> bool:
    """A null the filing itself refuses to quantify. An unmentioned metric is not one."""
    if (raw.get("excerpt") or "").strip():
        return True
    return any(phrase in (raw.get("reason") or "").lower() for phrase in DECLINED)


def entry(raw: dict) -> dict:
    """One extracted metric as a plain dict, with its evidence stamped on."""
    value, confidence = raw.get("value"), raw.get("confidence")
    # A figure that is not stated has nothing to cite, whatever the model quoted.
    excerpt, source_id = ("", "") if value is None else (raw.get("excerpt") or "", raw.get("source_id") or "")
    reason = raw.get("reason") or ""
    if excerpt and unscaled(excerpt) and (confidence or 0) > CAP:
        confidence, reason = CAP, f"figure has no scale unit; {reason}".strip()
    if value is None:
        confidence = min(confidence or 0.0, CAP)  # never above the floor, so gate 1 flags it
    return {"value": value, "excerpt": excerpt, "confidence": confidence,
            "reason": reason, "model_id": model.MODEL_ID, "produced_at": model.now(),
            "step": "document_analyser", "source_id": source_id}


async def analyse(state: MemoState, deps) -> MemoState:
    """Ask once over all sources, assess risk, check the evidence, then choose the next process.

    Weak values or high risk go to a senior analyst; otherwise straight to the memo.
    """
    text = "\n\n".join(f"[{doc_id}]\n{body}" for doc_id, body in state["sources"].items())
    raw = parse(await deps["ask"](PROMPT.format(schema=", ".join(SCHEMA), text=text)))
    values = {name: entry(value) for name, value in raw.items()
              if name in SCHEMA and (value.get("value") is not None or declined(value))}
    checked = evidence_check(await risk_assessor.assess({**state, "values": values}, deps))
    return {**checked, "status": Status.SENIOR_REVIEW if needs_gate1(checked) else Status.SYNTHESIS}
