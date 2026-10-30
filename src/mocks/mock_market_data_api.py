"""
NovaMark Capital, Mock Market Data API (Bloomberg-style)
=========================================================
Stand-in for the market-data endpoint NovaMark's research desk already calls.

Run:
    pip install fastapi uvicorn
    uvicorn mock_market_data_api:app --port 8000

Spec:
    GET /api/v1/market/quote?ticker={T}&fields=price,pe_ratio,ev_ebitda,debt_equity,revenue_growth
    Authorization: Bearer MOCK_API_KEY_12345
    Tickers: AAPL, MSFT, GOOGL, TSM, NVDA
    Every 5th authorized call returns 429 with Retry-After.
"""

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import datetime, timezone
import itertools

app = FastAPI(title="NovaMark Mock Market Data", version="1.0.0")

VALID_TOKEN = "MOCK_API_KEY_12345"

QUOTES = {
    "AAPL":  {"price": 231.40, "pe_ratio": 35.1, "ev_ebitda": 24.8, "debt_equity": 1.45, "revenue_growth": 0.061},
    "MSFT":  {"price": 478.22, "pe_ratio": 37.6, "ev_ebitda": 26.2, "debt_equity": 0.38, "revenue_growth": 0.124},
    "GOOGL": {"price": 192.05, "pe_ratio": 26.4, "ev_ebitda": 18.9, "debt_equity": 0.11, "revenue_growth": 0.139},
    "TSM":   {"price": 188.77, "pe_ratio": 29.0, "ev_ebitda": 15.3, "debt_equity": 0.27, "revenue_growth": 0.336},
    "NVDA":  {"price": 134.29, "pe_ratio": 52.7, "ev_ebitda": 47.1, "debt_equity": 0.16, "revenue_growth": 0.942},
}

_counter = itertools.count(1)


def _check_auth(authorization: Optional[str]) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    if authorization.split(" ", 1)[1].strip() != VALID_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/api/v1/market/quote")
def quote(
    ticker: str = Query(..., description="One of AAPL, MSFT, GOOGL, TSM, NVDA"),
    fields: str = Query("price", description="Comma-separated field list"),
    authorization: Optional[str] = Header(default=None),
):
    _check_auth(authorization)

    # Every 5th authorized call is rate-limited.
    if next(_counter) % 5 == 0:
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "message": "Too many requests. Back off and retry."},
            headers={"Retry-After": "2"},
        )

    t = ticker.upper()
    if t not in QUOTES:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker}")

    requested = [f.strip() for f in fields.split(",") if f.strip()]
    available = QUOTES[t]
    data = {f: available.get(f) for f in requested}
    missing = [f for f in requested if f not in available]

    return {
        "ticker": t,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "mock-market-data",
        "data": data,
        "unrecognized_fields": missing,  # client should note these, not crash
    }


@app.get("/health")
def health():
    return {"status": "ok"}
