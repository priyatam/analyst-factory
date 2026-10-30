"""
Smoke test for the market data mock. Confirms the REST API (port 8000) is up and
behaving. This does NOT evaluate the solution, it only checks that the mock responds.

Start the server first:
    uvicorn mocks.mock_market_data_api:app --port 8000
Then:
    pip install requests
    python smoke_test.py
"""

import sys

try:
    import requests
except ImportError:
    print("Please `pip install requests` to run the smoke test.")
    sys.exit(1)

REST = "http://localhost:8000"
TOKEN = {"Authorization": "Bearer MOCK_API_KEY_12345"}


def check_rest():
    print("[REST] quote NVDA ...")
    r = requests.get(f"{REST}/api/v1/market/quote",
                     params={"ticker": "NVDA", "fields": "price,pe_ratio,debt_equity"},
                     headers=TOKEN, timeout=5)
    r.raise_for_status()
    print("       ->", r.json()["data"])

    print("[REST] checking 429 appears within a few calls ...")
    saw_429 = False
    for _ in range(6):
        rr = requests.get(f"{REST}/api/v1/market/quote",
                          params={"ticker": "AAPL", "fields": "price"},
                          headers=TOKEN, timeout=5)
        if rr.status_code == 429:
            saw_429 = True
            break
    print("       -> 429 observed:", saw_429)


if __name__ == "__main__":
    check_rest()
    print("\nSmoke test complete. If you saw a 429, the market mock is healthy.")
