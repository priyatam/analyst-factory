"""Settings, the model call, and the clock: the edges the processes reach through `Deps`.

Everything here touches the outside world. The steps in the pipe receive these through
`Deps`, so they stay pure and testable.
"""
import asyncio
import os
import sys
from pathlib import Path

from strands import Agent
from strands.models import BedrockModel

from .otel import span


# --- settings -------------------------------------------------------------------------------

MODEL_ID = "us.anthropic.claude-sonnet-4-6"  # must match the IAM profile in deploy.py
REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"

# Resolved from the installed layout, so local and runtime agree: the code zip puts `data/` and
# `mocks/` beside the `novamark` package, which is the same relative position as in `src/`.
_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = _ROOT / "data"

MARKET_API_URL = os.getenv("MARKET_API_URL")  # unset: the bundled mock runs in process
MARKET_API_KEY = os.getenv("MARKET_API_KEY")  # for a real MARKET_API_URL; the in-process mock needs none
MARKET_FIELDS = ("price", "pe_ratio", "ev_ebitda", "debt_equity", "revenue_growth")
KB_COMMAND = [sys.executable, str(_ROOT / "mocks" / "mock_mcp_research_kb_server.py")]

CONFIDENCE_FLOOR = 0.75  # gate 1 fires below this, or on high risk
MAX_REVISIONS = 3
RISK_THRESHOLDS = {"confidence": 0.75}  # below this, a low risk is raised to medium

# --- the model ------------------------------------------------------------------------------

SYSTEM = "You are a meticulous equity research analyst. Answer with the requested format only."


def agent() -> Agent:
    """One Strands agent, no tools. Built per call so no history carries between documents."""
    return Agent(model=BedrockModel(model_id=MODEL_ID, region_name=REGION),
                 system_prompt=SYSTEM, tools=[], callback_handler=None)


async def ask(prompt: str) -> str:
    """The blocking SDK call, off the event loop. The prompt stays off the span."""
    with span("model.call", model_id=MODEL_ID):
        return await asyncio.to_thread(lambda: str(agent()(prompt)))

# --- the clock ------------------------------------------------------------------------------

def now() -> str:
    """ISO 8601, UTC. Every extracted value and decision stamps itself through this."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

