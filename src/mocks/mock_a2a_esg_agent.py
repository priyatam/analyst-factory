"""
NovaMark Capital, Mock A2A ESG Specialist Agent
================================================
A protocol-faithful (simplified) Agent-to-Agent server for the external
ESG specialist referenced in Wand_SA_Assignment_1_Build_NovaMark.docx.

Run:
    pip install fastapi uvicorn
    uvicorn mock_a2a_esg_agent:app --port 8001

Discovery:
    GET /.well-known/agent-card.json        (current path)
    GET /.well-known/agent.json             (legacy alias; also served)

Work:
    POST /  with JSON-RPC 2.0 body.
    Methods:
      - message/send   -> creates a Task, returns it in "submitted" then drives it
      - tasks/get      -> poll a task by id (lifecycle: submitted -> working -> completed)

Lifecycle note (matches the take-home):
    A task moves submitted -> working -> completed. Output is an Artifact
    composed of typed Parts (TextPart + DataPart).

AUDIT-GAP teaching point:
    This agent does its ESG scoring internally and returns ONLY the final
    artifact. The caller (Wand) can capture what it sent and what it got
    back, but NOT this agent's internal reasoning or intermediate steps.
    That partial-audit reality is exactly what the architect take-home
    asks the candidate to reason about.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uuid

app = FastAPI(title="Mock A2A ESG Agent", version="1.0.0")

AGENT_CARD = {
    "name": "ESG Specialist Agent",
    "description": "Provides ESG scoring and controversy screening for public equities.",
    "version": "1.0.0",
    "protocolVersion": "0.3.0",
    "url": "http://localhost:8001/",
    "capabilities": {"streaming": False, "pushNotifications": True},
    "defaultInputModes": ["application/json"],
    "defaultOutputModes": ["application/json"],
    "skills": [
        {"id": "esg_scoring", "name": "ESG Scoring",
         "description": "Returns E/S/G sub-scores and a composite ESG score for a ticker."},
        {"id": "controversy_screening", "name": "Controversy Screening",
         "description": "Flags recent ESG controversies for a ticker."},
    ],
    "securitySchemes": {"apiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}},
}

# Pre-baked ESG results (the agent's "internal" knowledge, not exposed step-by-step).
ESG = {
    "AAPL":  {"esg_score": 72, "e": 68, "s": 74, "g": 75, "controversies": ["supply-chain labor audit 2025"]},
    "MSFT":  {"esg_score": 81, "e": 79, "s": 80, "g": 84, "controversies": []},
    "GOOGL": {"esg_score": 66, "e": 70, "s": 60, "g": 68, "controversies": ["antitrust proceedings", "data-privacy fine 2025"]},
    "TSM":   {"esg_score": 70, "e": 64, "s": 72, "g": 74, "controversies": ["water-usage scrutiny 2025"]},
    "NVDA":  {"esg_score": 69, "e": 66, "s": 67, "g": 74, "controversies": ["export-control compliance review"]},
}

# In-memory task store.
TASKS = {}


def _rpc_result(i, r): return {"jsonrpc": "2.0", "id": i, "result": r}
def _rpc_error(i, c, m): return {"jsonrpc": "2.0", "id": i, "error": {"code": c, "message": m}}


def _build_artifact(ticker: str):
    data = ESG.get(ticker.upper())
    if not data:
        return None
    summary = (f"ESG composite for {ticker.upper()}: {data['esg_score']}/100 "
               f"(E {data['e']}, S {data['s']}, G {data['g']}). "
               f"Controversies: {', '.join(data['controversies']) or 'none'}.")
    return {
        "artifactId": str(uuid.uuid4()),
        "name": "esg_result",
        "parts": [
            {"kind": "text", "text": summary},
            {"kind": "data", "data": {"ticker": ticker.upper(), **data, "confidence": 0.86}},
        ],
    }


@app.get("/.well-known/agent-card.json")
def agent_card():
    return AGENT_CARD


@app.get("/.well-known/agent.json")
def agent_card_legacy():
    # Legacy alias retained for older tooling.
    return AGENT_CARD


@app.post("/")
async def rpc(request: Request):
    body = await request.json()
    method = body.get("method")
    i = body.get("id")
    params = body.get("params", {}) or {}

    if method == "message/send":
        # Expect a message whose data part carries {task_type, ticker}.
        msg = params.get("message", {})
        parts = msg.get("parts", [])
        payload = {}
        for p in parts:
            if p.get("kind") == "data":
                payload = p.get("data", {})
        ticker = payload.get("ticker", "")
        task_id = str(uuid.uuid4())
        # Create the task; mark working immediately, complete on first poll.
        artifact = _build_artifact(ticker)
        if artifact is None:
            return JSONResponse(_rpc_error(i, -32602, f"Unknown ticker {ticker}"))
        TASKS[task_id] = {
            "id": task_id,
            "_artifact": artifact,
            "_polls": 0,
            "status": {"state": "submitted"},
        }
        return JSONResponse(_rpc_result(i, {"id": task_id, "status": {"state": "submitted"}}))

    if method == "tasks/get":
        task_id = params.get("id")
        task = TASKS.get(task_id)
        if not task:
            return JSONResponse(_rpc_error(i, -32001, f"No task {task_id}"))
        # Drive the lifecycle across polls: submitted -> working -> completed.
        task["_polls"] += 1
        if task["_polls"] == 1:
            task["status"] = {"state": "working"}
            return JSONResponse(_rpc_result(i, {"id": task_id, "status": task["status"]}))
        task["status"] = {"state": "completed"}
        return JSONResponse(_rpc_result(i, {
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": [task["_artifact"]],
        }))

    return JSONResponse(_rpc_error(i, -32601, f"Method not found: {method}"))


@app.get("/health")
def health():
    return {"status": "ok"}
