"""AgentCore Runtime entrypoint, also served locally on :8080.

The runtime launches this file as a script (`python novamark/agent.py`), so `sys.path[0]` is the
package directory and the dependencies beside it are not importable. The path fix precedes every
other import.

The runtime allows 30s to initialize, so only the app is built here; the pipeline imports on first
use. Unhandled exceptions are logged with a traceback before being re-raised, because otherwise
the caller only sees an opaque 500.
"""
import logging
import sys
import traceback
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parents[1]
if str(_CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CODE_ROOT))

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

log = logging.getLogger("novamark")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> dict:
    from novamark import orchestrator

    handlers = {"new_request": orchestrator.start, "decision": orchestrator.decide_sync}
    try:
        return handlers[payload["type"]](payload)
    except Exception:
        log.error("invoke failed for %s\n%s", payload.get("type"), traceback.format_exc())
        raise


if __name__ == "__main__":
    from novamark import model

    print(f"novamark ready: {model.MODEL_ID} market {model.MARKET_API_URL or 'in-process mock'}")
    app.run()
