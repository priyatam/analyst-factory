"""
NovaMark Capital, Mock MCP Research-KB Server
==============================================
Exposes NovaMark's internal research knowledge base as MCP primitives:
  - tool:     search_research_kb(query, ticker, max_results)
  - resource: research://memos/{ticker}/history

Speaks JSON-RPC 2.0. This stub uses stdio (the local transport) so it runs with no
dependencies. In production it moves to Streamable HTTP behind AgentCore Gateway, where
tenant identity and isolation come from the verified JWT rather than the request body.

Run:
    python mock_mcp_research_kb_server.py
Then send newline-delimited JSON-RPC on stdin, e.g.:
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
    {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_research_kb","arguments":{"query":"valuation","ticker":"NVDA"}}}
    {"jsonrpc":"2.0","id":3,"method":"resources/read","params":{"uri":"research://memos/AAPL/history"}}

TENANT-ISOLATION HOOK (read this):
    Every request MAY carry params._meta.tenant_id. This stub only serves
    tenant "novamark". A request with a different tenant_id is rejected.
    A real server would validate this from an auth claim on the transport,
    NOT from a client-supplied field, call that out in your design.
"""

import sys
import json

PROTOCOL_VERSION = "2025-11-25"
SERVED_TENANT = "novamark"

# Seeded historical memos, >= 3 per ticker.
MEMOS = {
    "AAPL": [
        {"analyst": "R. Haddad", "date": "2025-08-12", "thesis": "Services margin expansion underappreciated", "target_price": 245, "recommendation": "Buy"},
        {"analyst": "L. Okonkwo", "date": "2025-11-03", "thesis": "Hardware cycle maturing; growth decelerating", "target_price": 220, "recommendation": "Hold"},
        {"analyst": "R. Haddad", "date": "2026-01-20", "thesis": "AI feature refresh a modest tailwind", "target_price": 238, "recommendation": "Hold"},
    ],
    "MSFT": [
        {"analyst": "S. Verma", "date": "2025-09-01", "thesis": "Azure AI workloads driving re-acceleration", "target_price": 500, "recommendation": "Buy"},
        {"analyst": "S. Verma", "date": "2025-12-10", "thesis": "Capex intensity a near-term margin drag", "target_price": 470, "recommendation": "Buy"},
        {"analyst": "M. Lindqvist", "date": "2026-02-15", "thesis": "Copilot monetization still unproven at scale", "target_price": 455, "recommendation": "Hold"},
    ],
    "GOOGL": [
        {"analyst": "M. Lindqvist", "date": "2025-07-22", "thesis": "Search resilient despite AI disruption fears", "target_price": 205, "recommendation": "Buy"},
        {"analyst": "L. Okonkwo", "date": "2025-10-30", "thesis": "Cloud profitability inflection reached", "target_price": 210, "recommendation": "Buy"},
        {"analyst": "S. Verma", "date": "2026-01-28", "thesis": "Regulatory overhang caps multiple", "target_price": 195, "recommendation": "Hold"},
    ],
    "TSM": [
        {"analyst": "R. Haddad", "date": "2025-08-30", "thesis": "Foundry pricing power intact; AI demand strong", "target_price": 215, "recommendation": "Buy"},
        {"analyst": "M. Lindqvist", "date": "2025-11-18", "thesis": "Geopolitical risk premium persists", "target_price": 195, "recommendation": "Buy"},
        {"analyst": "L. Okonkwo", "date": "2026-02-02", "thesis": "Capacity expansion de-risks supply", "target_price": 205, "recommendation": "Buy"},
    ],
    "NVDA": [
        {"analyst": "S. Verma", "date": "2025-09-15", "thesis": "Data-center demand outrunning supply", "target_price": 165, "recommendation": "Buy"},
        {"analyst": "R. Haddad", "date": "2025-12-05", "thesis": "Customer concentration a tail risk", "target_price": 140, "recommendation": "Hold"},
        {"analyst": "M. Lindqvist", "date": "2026-01-30", "thesis": "Next-gen architecture sustains lead", "target_price": 155, "recommendation": "Buy"},
    ],
}


def _result(i, r): return {"jsonrpc": "2.0", "id": i, "result": r}
def _error(i, c, m): return {"jsonrpc": "2.0", "id": i, "error": {"code": c, "message": m}}


def _tenant_ok(params) -> bool:
    meta = (params or {}).get("_meta", {}) or {}
    tid = meta.get("tenant_id", SERVED_TENANT)  # default to served tenant if unset
    return tid == SERVED_TENANT


TOOLS = [{
    "name": "search_research_kb",
    "description": "Search NovaMark's internal research memos.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "ticker": {"type": "string"},
            "max_results": {"type": "integer", "default": 5},
        },
        "required": ["query", "ticker"],
    },
}]


def handle(req):
    method = req.get("method")
    i = req.get("id")
    params = req.get("params", {}) or {}

    if method == "initialize":
        return _result(i, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "novamark-research-kb", "version": "1.0.0"},
        })

    if not _tenant_ok(params):
        return _error(i, -32001, "Tenant not authorized for this server")

    if method == "tools/list":
        return _result(i, {"tools": TOOLS})

    if method == "resources/list":
        uris = [{"uri": f"research://memos/{t}/history", "name": f"{t} memo history",
                 "mimeType": "application/json"} for t in MEMOS]
        return _result(i, {"resources": uris})

    if method == "resources/read":
        uri = params.get("uri", "")
        # research://memos/{ticker}/history
        try:
            ticker = uri.split("research://memos/")[1].split("/")[0].upper()
        except Exception:
            return _error(i, -32602, f"Malformed resource uri: {uri}")
        if ticker not in MEMOS:
            return _error(i, -32602, f"No memo history for {ticker}")
        return _result(i, {"contents": [{
            "uri": uri, "mimeType": "application/json",
            "text": json.dumps(MEMOS[ticker], indent=2),
        }]})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        if name != "search_research_kb":
            return _error(i, -32602, f"Unknown tool: {name}")
        ticker = (args.get("ticker") or "").upper()
        q = (args.get("query") or "").lower()
        maxr = args.get("max_results", 5)
        memos = MEMOS.get(ticker, [])
        hits = [m for m in memos if q in m["thesis"].lower() or q in m["recommendation"].lower()] or memos
        hits = hits[:maxr]
        return _result(i, {
            "content": [{"type": "text", "text": json.dumps({"ticker": ticker, "matches": hits}, indent=2)}],
            "isError": False,
        })

    return _error(i, -32601, f"Method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_error(None, -32700, "Parse error")) + "\n"); sys.stdout.flush(); continue
        sys.stdout.write(json.dumps(handle(req)) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    main()
