"""Tests that call a deployed AgentCore Runtime over HTTPS.

These need a real deployment and AWS credentials, so they skip unless
`NOVAMARK_RUNTIME_ARN` is set. Everything else in the suite runs offline.

    export NOVAMARK_RUNTIME_ARN=arn:aws:bedrock-agentcore:<region>:<account>:runtime/...
    uv run pytest tests/test_deployed.py -v

The request is SigV4-signed with the caller's credentials, which is what the runtime expects.
A run costs one model call, so the module is opt-in rather than part of the default run.
"""
import json
import os
import uuid

import pytest

ARN = os.getenv("NOVAMARK_RUNTIME_ARN")
from novamark.model import REGION  # noqa: E402

pytestmark = [
    pytest.mark.allow_network,
    pytest.mark.skipif(not ARN, reason="set NOVAMARK_RUNTIME_ARN to call a deployed runtime"),
]


def call(payload: dict) -> dict:
    """POST to the runtime's invoke endpoint with SigV4. The ARN goes in URL-encoded."""
    import urllib.error
    import urllib.parse
    import urllib.request

    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    assert ":bedrock-agentcore:" in ARN and ":runtime/" in ARN, (
        f"NOVAMARK_RUNTIME_ARN must be the runtime ARN (the RuntimeArn stack output), not {ARN}")
    encoded = urllib.parse.quote(ARN, safe="")
    url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{encoded}/invocations"
    body = json.dumps(payload)
    signed = AWSRequest(method="POST", url=url, data=body,
                        headers={"Content-Type": "application/json"})
    SigV4Auth(boto3.Session().get_credentials(), "bedrock-agentcore", REGION).add_auth(signed)

    req = urllib.request.Request(url, data=body.encode(), headers=dict(signed.headers),
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise AssertionError(f"HTTP {e.code}: {e.read().decode()[:500]}") from None


def test_a_new_request_stops_at_a_review():
    """One model call. Asserts the deployed runtime returns a packet, not a stack trace."""
    payload = {"type": "new_request",
               "request": {"ticker": "NVDA", "asset_class": "equity", "analysis_type": "memo"}}

    packet = call(payload)

    assert packet["gate"] in ("senior_review", "compliance_review")
    assert packet["run_id"]
    assert isinstance(packet["values"], dict)


def test_an_unknown_payload_type_is_rejected():
    """The dispatcher is a dict lookup, so an unknown type must not silently do nothing."""
    with pytest.raises(Exception):
        call({"type": "not_a_real_type"})


def test_a_decision_resumes_the_same_run():
    """Two model calls. Proves the S3 state outlives the runtime session."""
    packet = call({"type": "new_request",
                   "request": {"ticker": "AAPL", "asset_class": "equity",
                               "analysis_type": "memo"}})

    # Walk the path the packet actually reported rather than assuming a clean run.
    step = packet
    while step.get("gate"):
        gate = step["gate"]
        roles = ["senior_analyst"] if gate == "senior_review" else ["compliance_officer"]
        step = call({"type": "decision", "run_id": packet["run_id"], "roles": roles,
                     "decision": {"gate": gate, "action": "approve",
                                  "reviewer": "deployed-test", "comment": "automated check",
                                  "id": str(uuid.uuid4())}})

    assert step["status"] == "published"
    assert step["memo"]
