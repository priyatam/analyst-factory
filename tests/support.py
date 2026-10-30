"""Test doubles and builders. Imported by the tests, never by the package."""
import asyncio
import json


class Model:
    """Stands in for the model. Answers by prompt type.

    `extraction` may be one answer or a sequence: a revision can then return a better
    answer than the first attempt.
    """

    def __init__(self, extraction, reasons: str = '{"reasons": []}', memo: str = "MEMO"):
        self.extractions = [extraction] if isinstance(extraction, str) else list(extraction)
        self.reasons, self.memo = reasons, memo
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Extract these metrics" in prompt:
            return self.extractions.pop(0) if len(self.extractions) > 1 else self.extractions[0]
        if "List the concrete risks" in prompt:
            return self.reasons
        return self.memo


def weak_revenue() -> dict:
    """A real sentence, but unquantified: value null, low confidence. Gate 1 fires on it."""
    return {"value": None,
            "excerpt": "Export controls on advanced computing products may affect the business",
            "confidence": 0.2, "reason": "no figure given", "source_id": "DOC-NVDA-10K"}


def fields(**overrides) -> str:
    """A model answer with two confident metrics, plus any overrides.

    The excerpts are real sentences from the NVDA excerpt, so the evidence check passes.
    """
    base = {
        "revenue": {"value": 130.6, "excerpt": "Revenue for fiscal 2026 was $130.6 billion",
                    "confidence": 0.9, "reason": "stated", "source_id": "DOC-NVDA-10K"},
        "gross_margin": {"value": 74.6, "excerpt": "Gross margin was 74.6%",
                         "confidence": 0.9, "reason": "stated", "source_id": "DOC-NVDA-10K"},
    }
    base.update(overrides)
    return json.dumps({"values": base})


def run(coro):
    return asyncio.run(coro)
