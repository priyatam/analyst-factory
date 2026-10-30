"""Run both paths against the deployed AgentCore Runtime.

    export NOVAMARK_RUNTIME_ARN=<runtime ARN>
    uv run python src/demo.py

Each request is signed with SigV4 using your AWS credentials. A clean run (AAPL) and a gated
run (NVDA) each go through every review gate to a published memo. Every new run makes real model
calls, billed to the account that owns the runtime.
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from novamark.model import REGION
ROLES = {"senior_review": "senior_analyst", "compliance_review": "compliance_officer"}


def invoke(arn: str, payload: dict) -> dict:
    """POST one payload to the runtime. The ARN goes in the URL encoded."""
    url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{urllib.parse.quote(arn, safe='')}/invocations"
    body = json.dumps(payload)
    signed = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "bedrock-agentcore", REGION).add_auth(signed)
    req = urllib.request.Request(url, data=body.encode(), headers=dict(signed.headers), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:500]}")


def approve(arn: str, packet: dict) -> dict:
    """Approve the gate the run stopped at."""
    return invoke(arn, {"type": "decision", "run_id": packet["run_id"], "roles": [ROLES[packet["gate"]]],
                        "decision": {"gate": packet["gate"], "action": "approve", "reviewer": "demo",
                                     "comment": "approved in the demo", "id": str(uuid.uuid4())}})


def show(packet: dict) -> None:
    print(f"   stopped at: {packet['gate']} ({packet['role']})")
    print(f"   flagged: {packet['flagged'] or 'none'}")
    print(f"   risk: {packet['risk']['level']} {packet['risk']['reasons']}")
    print(f"   gaps: {[g['source'] for g in packet['gaps']] or 'none'}")
    for name, v in packet["values"].items():
        print(f"   {name} = {v['value']}  (confidence {v['confidence']})  \"{v['excerpt']}\"")


def main() -> None:
    arn = os.getenv("NOVAMARK_RUNTIME_ARN") or sys.exit("set NOVAMARK_RUNTIME_ARN to the deployed runtime")
    if ":runtime/" not in arn:
        sys.exit(f"not an AgentCore runtime ARN (arn:aws:bedrock-agentcore:...:runtime/...): {arn}")
    for name, ticker in (("clean run", "AAPL"), ("gated run", "NVDA")):
        print(f"\n== {name}: {ticker} ==")
        step = invoke(arn, {"type": "new_request",
                            "request": {"ticker": ticker, "asset_class": "equity", "analysis_type": "memo"}})
        while step.get("gate"):
            show(step)
            print(f"   approving {step['gate']}")
            step = approve(arn, step)
        print(f"   {step['status']} | decisions: {len(step['decisions'])}")
        print(f"   memo: {step['memo']}")


if __name__ == "__main__":
    main()
