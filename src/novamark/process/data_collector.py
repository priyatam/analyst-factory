"""Data collector: the market REST quote and the filings index. No agent.

The market API returns 429 on every fifth call, so the retry and its Retry-After wait live
here, where the requirement puts them. A source that never arrives is a gap, not a crash.
"""
import csv
from pathlib import Path

import httpx

from .. import model
from ..state import Gap, MemoState, Status


class RateLimited(Exception):
    """Upstream asked us to slow down. `after` is its Retry-After in seconds."""

    def __init__(self, after: float = 1.0):
        super().__init__(f"rate limited, retry after {after}s")
        self.after = after


async def quote_once(ticker: str) -> dict:
    """One market call. Raises `RateLimited` on 429 so the caller can back off.

    With `MARKET_API_URL` set it goes over HTTP. Without it the bundled mock runs in this
    process, so a local run and the deployed runtime work with nothing else to start.
    """
    params = {"ticker": ticker, "fields": ",".join(model.MARKET_FIELDS)}
    path = "/api/v1/market/quote"
    if model.MARKET_API_URL:
        headers = {"Authorization": f"Bearer {model.MARKET_API_KEY}"}
        r = httpx.get(model.MARKET_API_URL + path, params=params, headers=headers, timeout=10)
    else:
        from mocks.mock_market_data_api import VALID_TOKEN, app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://mock") as c:
            r = await c.get(path, params=params, headers={"Authorization": f"Bearer {VALID_TOKEN}"})
    if r.status_code == 429:
        raise RateLimited(float(r.headers.get("Retry-After", 1)))
    r.raise_for_status()
    return r.json()


def quote(send=quote_once, *, times: int = 3, sleep=None):
    """A quote call that honours Retry-After, up to `times` attempts.

    `send` is the transport, so a test can replace it.
    """
    import asyncio

    async def attempt(ticker: str) -> dict:
        for n in range(1, times + 1):
            try:
                return await send(ticker)
            except RateLimited as rl:
                if n == times:
                    raise
                await (sleep or asyncio.sleep)(rl.after)

    return attempt


def filings(ticker: str) -> dict[str, dict]:
    """Rows of the filings CSV for this ticker, keyed by doc id, with the text attached."""
    path = Path(model.DATA_DIR) / "filings_metadata.csv"
    with path.open() as f:
        rows = [r for r in csv.DictReader(f) if r["ticker"].upper() == ticker.upper()]
    return {r["doc_id"]: {**r, "text": (path.parent / r["filename"]).read_text()} for r in rows}


async def collect(state: MemoState, deps) -> MemoState:
    """Sources and freshness, or gaps. Hands the run on to `document_analyser`."""
    ticker = state["request"]["ticker"]
    docs = deps["filings"](ticker)
    gaps: list[Gap] = []
    if not docs:
        gaps.append(Gap(source="filings", reason=f"no filing for {ticker}"))

    sources = {doc_id: doc["text"] for doc_id, doc in docs.items()}
    freshness = {doc_id: doc["filing_date"] for doc_id, doc in docs.items()}
    try:
        market = await deps["quote"](ticker)
        sources[f"market:{ticker}"] = str(market["data"])
        freshness["market"] = market["as_of"]
    except Exception as e:
        gaps.append(Gap(source="market", reason=str(e)))
    return {**state, "sources": sources, "freshness": freshness,
            "gaps": [*state["gaps"], *gaps], "status": Status.DOCUMENT_ANALYSER}
