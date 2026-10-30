# Architecture: Research Workforce

The harness takes one request (a ticker, an asset class and an analysis type) and produces an investment memo that can be audited, with a senior analyst and a compliance officer approving it along the way. It is a linear pipeline over a single typed state, and the model is limited to three prompts. The table below maps each requirement to the component that meets it, and the rest of the page describes how those components fit together. The alternatives we rejected are in [decisions.md](decisions.md), and open issues are in [code-reviews.md](code-reviews.md).

| Requirement | Component |
| --- | --- |
| One clean run and one flagged run, end to end | [Orchestrator](../src/novamark/orchestrator.py) |
| Market data and filings with freshness; back off on 429 | [Data collector](../src/novamark/process/data_collector.py) |
| Every metric has a citation and a confidence; risk scored against configurable thresholds | [Document analyser](../src/novamark/process/document_analyser.py), [risk assessor](../src/novamark/process/risk_assessor.py) |
| Prior firm research; the run continues if the server fails | [Knowledge base](../src/novamark/knowledge_base.py) (MCP) |
| No value passes without a citation and a confidence | [Evidence check](../src/novamark/process/evidence_check.py) |
| Analyst approval before the memo, compliance approval before publish | [Gates](../src/novamark/process/gates.py) |
| Complete audit of AI output | [Snapshot store](../src/novamark/state.py) |
| Customer data stays in their cloud | [Bedrock and S3 in one account](../src/deploy.py) |

Four properties shape the design:

1. **Asynchronous pipeline.** Independent sources are fetched at the same time.
2. **State machine.** Every step is a named `status`, and a run resumes from stored state process.
3. **Immutable snapshots.** Each one is written once and never edited.
4. **Idempotent decisions.** A retried decision is applied only once.

[Strands Agents](https://strandsagents.com/) is used only for reasoning. It runs a single `Agent` with a fixed system prompt and no tools ([model.py](../src/novamark/model.py)), and that agent does three jobs: it extracts metrics, lists the risks stated in the text, and writes the memo. Everything else, including fetching data, checking evidence and moving between steps, is ordinary Python. This keeps the path that produces evidence the same from run to run, and it means there is no tool routing to reason about.

## The state machine

A run is one `MemoState` dict ([state.py](../src/novamark/state.py)). Its `status`, one of the [`Status`](../src/novamark/state.py) values, is the state the run is in, and it also names the process that runs next. The [orchestrator](../src/novamark/orchestrator.py) is a loop on `status`, so nothing else decides the order of steps.

![State machine](img/state-machine.svg)

**State Schema**

A run is one entity, its metrics are attribute-value entries, and every save is a snapshot in S3.

```python
class MemoState(TypedDict):
    run_id: str                  # the entity, and the store key
    request: Request             # ticker, asset_class, analysis_type
    status: Status               # the process that runs next
    revision: int                # rejections so far, capped at three
    sources: dict[str, str]      # source id -> exact text, so a citation can be checked
    values: dict[str, dict]      # metric name -> value plus evidence
    risk: Risk | None            # level and reasons
    prior_memos: list[dict] | None   # None if the knowledge base failed
    gaps: list[Gap]              # what was unavailable, and why
    freshness: dict[str, str]    # when each source was last current
    decisions: list[Decision]    # append-only review log
    memo: str | None
    applied: list[str]           # decision ids already applied
```

`values` is what a reviewer reads. Each key is a metric the analyser looked for, and each entry is one finding: the figure, the sentence it came from, and how sure the model is. This is the entry for `segment_gaming`, read from a garbled table in the NVDA filing:

```python
"segment_gaming": {
    "value": 11900,
    "excerpt": "Gaming               $11,900",
    "confidence": 0.5,
    "reason": "figure has no scale unit; segment table",
    "model_id": "us.anthropic.claude-sonnet-4-6",
    "produced_at": "2026-10-29T09:14:48Z",
    "step": "document_analyser",
    "source_id": "DOC-NVDA-10K"}
```

The filing prints `Gaming $11,900` beside `$115.2 billion` with no scale word, so the code caps confidence at 0.5 and the run stops at `senior_review`. A metric the filing does not state stays in `values` with a null value. [`evidence_check`](../src/novamark/process/evidence_check.py) requires every non-null value to have an excerpt that appears in `sources[source_id]`, and a confidence. The code, not the model, records `model_id`, `produced_at`, and `step`.

**Execution**

![Execution: how the orchestrator runs the transitions](img/execution.svg)

**Snapshot Log**

Each time a run stops, the orchestrator appends the whole state as the next numbered object under the run, and never rewrites one. This is the object written when a flagged run reaches `compliance_review` after the senior analyst approved (trimmed):

```
runs/run-1/001-compliance_review.json
{ "status": "compliance_review", "revision": 0,
  "values": {"segment_gaming": {"value": 11900, "confidence": 0.5}},
  "decisions": [{"gate": "senior_review", "action": "approve", "reviewer": "pri"}],
  "memo": "NVDA investment memo ..." }
```

`load` returns the highest key. Listing the prefix replays the run, so an auditor who opens `001` sees the state the compliance officer saw.

## Runtime

One AgentCore Runtime session handles each run, in the customer's AWS account.

The session enters through `BedrockAgentCoreApp` and a single synchronous `invoke` ([agent.py](../src/novamark/agent.py)). That is the only place `asyncio.run` is called; everything below it is awaited. Model calls go to Bedrock under the customer's IAM. Bedrock Guardrails are not configured, so the evidence check is currently the only rule applied to model output.

![Where each part runs](img/deployment.svg)

State is kept in S3 because the session ends between the two reviews. Inference uses the `us.` Bedrock inference profile, which can route a request to another US region, so a customer that requires a single region would need a regional model id instead.

The market quote and the prior research are case-study mocks inside the agent, locally and on AWS. NovaMark's market system, research database, and ESG provider are not connected. Set `MARKET_API_URL` to call a market service over HTTP instead of the in-process mock.

## Scalability and reliability

**Scale.** Each run is one AgentCore Runtime session: a serverless microVM with its own CPU, memory and filesystem, started on demand and billed for active use. There is no fleet to size, and one run cannot read or slow another. The code keeps nothing in the session. A run's whole state is a snapshot in S3 and every process is a function from one state to the next, so any session can resume any run and more load means more sessions, not a bigger one. A review costs nothing while it waits, because the session is not held open.

**Reliability.** The snapshot is the unit of recovery. If a session dies, the run resumes from its latest snapshot, which is the last review, or starts again if it never reached one. A decision with an id is applied once, so a retried call cannot double-apply. A snapshot is written once, so a retry cannot overwrite history. A failed source becomes a gap and the run continues, and a value that fails the evidence check stops the run before a reviewer sees it. A 429 from the market API is retried after its `Retry-After`.

A throttled Bedrock call is not retried, only the reviews and the end are saved, and two writers of the same run can collide on the snapshot count. Those limits are tracked in [code-reviews.md](code-reviews.md).

## Security

![Identity: how the agent that ran the memo got its identity](img/identity.svg)

**Humans.** Every request is signed with SigV4, so only an IAM principal allowed to invoke the runtime can start a run or send a decision. The reviewer name and roles are plain fields in the request: `gates.decide` checks the role and the decision log stores the name, but neither is tied to the signing principal. Any permitted caller can therefore claim any role, and nothing stops a requester approving their own memo. The fix is to take both from the verified identity and record `requested_by` at intake.

**The agent.** The memo is produced by one IAM role that the runtime service assumes for the session. Every Bedrock and S3 call is signed as that role, and each extracted value records the `model_id` and time that produced it. The model has no credentials and no tools, and `evidence_check` tests every value it returns. A request with `"model": "haiku"` uses Claude Haiku 4.5 for that invoke, which is what the deployed tests send. A memo request without it stays on Sonnet. The state bucket is KMS-encrypted, TLS-only and private, and each snapshot is written once. The role is broader than it should be: any Bedrock model, delete on the bucket, and no source account condition on its trust policy. These are tracked in [code-reviews.md](code-reviews.md).

## Failure

| Condition                                                               | Result                                                     |
| ----------------------------------------------------------------------- | ---------------------------------------------------------- |
| 429 from the market API                                                 | retry with `Retry-After`, up to three attempts, then a gap |
| Other market error, missing filing, unreachable knowledge base          | gap, no retry; the run continues and the memo states it    |
| Value without a citation or confidence; excerpt not found in its source | run stops with `EvidenceError`                             |
| Malformed model JSON                                                    | run stops                                                  |
| Failed store write                                                      | run stops; no packet is returned                           |

A gap is stated in the memo. A stop returns an error and no packet. A failed store write is not retried.

## Cost

The forecast is model inference. List price for Claude Sonnet 4.6 is $3 per million input tokens and $15 per million output tokens.

A memo that is approved without a rejection makes three calls: extract the figures, assess risk, and write the memo. The two reviews do not call the model. One published memo used 1,993 input tokens and 1,435 output tokens.

```text
1,993 / 1,000,000 × $3  = $0.006
1,435 / 1,000,000 × $15 = $0.022
                        = $0.028 per memo
```

Output tokens are about four-fifths of that. At this token count, 1,000 tickers are $28 and 100,000 tickers are $2,800.

## Assumptions

- The cloud provider is AWS. The run, the model call, and the saved state stay in the customer's account.
- The workforce is model agnostic. The model id is one setting, and this build uses Claude Sonnet 4.6.
- The firm's evaluation data set is available after the proof of concept, and production rollout uses it to evaluate performance and improve the operational efficiency of the workforce.

## Evals

The five success metrics are scored by a Strands experiment on labelled synthetic filings. The evaluator compares extracted figures with a hand-written key. There is no judge model. How to run it, and how to point Claude Code at the same cases, is in [evals.md](evals.md).

## What is not here

This version has no review UI, multi-ticker runs, self-correction, ESG data, AgentCore Gateway or configured Bedrock Guardrail. None of them would change the state model.
