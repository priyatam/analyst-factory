# Code reviews

Validation findings go in this file. A finding sits under one pillar — Security, Reliability, Operational excellence, Performance, Cost — or under Acceptance criteria. Under that heading it is P0, P1, or P2.

An acceptance item states the requirement, what the repo does now, and the change. A pillar item states the defect and the done line.

P0 is what NovaMark would refuse. P1 is the proof-of-concept bar. P2 is drawn and not built, or still an open question. The line under each item is the acceptance criterion.

## Security

**P0. An approval has to be an approval.** `gates.decide` takes the role and the reviewer name from the request body. Any caller who can invoke the runtime can claim `compliance_officer`, and the analyst who requested the memo can approve it.

Done when `gates.decide` rejects a decision whose `gate` is not the run's `status`. Intake stores `requested_by`. That identity cannot clear `senior_review` or `compliance_review`. Roles are read in one function, documented as a stand-in until they come from the signing principal.

**P1. Least privilege on the runtime role.** `deploy.py` allows `bedrock:InvokeModel` on every resource and delete on the state bucket. The trust policy has no source account or source ARN condition.

Done when the role can invoke only the pinned inference profile, with `bedrock:InferenceProfileArn` set. The state bucket allows `PutObject` and `GetObject` on `runs/*` and `ListBucket` on that prefix, and does not allow delete. Versioning is on. The trust policy has `aws:SourceAccount` and `aws:SourceArn`. Logs, traces, and workload identity match the AgentCore execution-role documentation.

**P2. Reviewer identity comes from the signature.** P0 above still trusts the caller to send roles.

Done when the identity diagram marks as claimed only what the request is still allowed to claim, and a decision's reviewer is the signing principal.

## Reliability

**P1. One snapshot sequence.** Local and S3 each count objects to name the next snapshot. Two writers can take the same number. A retried decision can then fail instead of returning the state unchanged.

Done when local and S3 keys are produced by one function. A second writer does not reuse a key. A repeated decision id returns the stored state and does not append another decision.

**P2. The value record can be audited.** `values` is `dict[str, dict]`. An amend replaces the entry and skips `evidence_check`. A metric has no period or unit. Confidence is the model's own number, capped only for a missing scale and a null. One value has one excerpt.

Done when each of these is either in the code or recorded in `docs/decisions.md`:

- The entry is a `TypedDict`. A misspelt evidence field fails the type checker.
- An amend cannot drop `excerpt` and `source_id` unless a decision says a human value needs no citation. The entry records who changed it.
- A metric carries a period and a unit, or the key includes the period, so two years of revenue have two places to live.
- The 0.75 floor is checked against a labelled sample, or the docs say the score is uncalibrated and only capped for a missing scale and a null.
- A figure taken from two sentences has a stated rule for its citation.

**[DONE]** **P2. A throttled model call stops the run.** A Bedrock 429 is not retried. `docs/architecture.md` states that a throttled call fails the run.

Done when `model.ask` backs off and retries, or the architecture states that a throttled call fails the run.

## Operational excellence

**P1. One way to build dependencies.** `agent.py`, the demo, and the tests each wire the market client and the knowledge base. The deployed runtime calls the mock market app in process and starts the mock knowledge base as a subprocess.

Done when those three call one factory. On AWS that factory uses the in-process mocks, and the code says they are mocks.

**P1. A deploy must not change the account.** `deploy.py` turns on Transaction Search for the whole account on every deploy.

Done when a deploy does not call that API unless asked. The demo reads the runtime ARN from the environment. `diag.py` and `repro.py` are gone.

**[DONE]** **P2. Spans the execution diagram already draws.** Each `advance` span carries `run_id`, `status`, and `revision`, and each model call span carries `model_id`. The demo reads the runtime log group and pretty-prints a subset of the trace. The user ran the demo and saw that printout, so a published run's spans were shown, not only an in-memory test.

Done when a published run shows a span for each pass of `advance`, carrying `run_id`, `status`, and `revision`, and a span for each model call, in the runtime log group.

**[DONE]** **P2. AgentCore Gateway, if it stays on the diagram.** It is not built. `docs/img/deployment.svg` does not draw it on the path a request takes.

Done when the deployment diagram includes Gateway only if a request reaches the market API and the knowledge base through it.

## Performance

**P1. The market call blocks the event loop.** `quote_once` uses a blocking HTTP client, so the quote and prior research run one after the other.

Done when the quote fetch awaits. A slow knowledge base does not wait behind it. A 429 still honours `Retry-After` for at most three attempts.

## Cost

**[DONE]** No change. Three model calls per run stay. Do not add a fourth to close a review comment.



## Acceptance criteria

NovaMark's written requirements in `docs/requirements.md`. Each item is the requirement, what the repo does instead, and the change.

**[DONE]** **P0. Working code must show two finished memos.**

Requirement. Deliverable 1, and component 1: one clean run, and one run that stops for low confidence or high risk. Both go through the workers, the MCP read, both approvals, and end as a published memo.

Done in `src/demo.py` and `README.md`. The default run is AAPL and skips `senior_review`. `uv run python src/demo.py --high-risk` is NVDA and stops at `senior_review`. Both continue through compliance to `published`.

**[DONE]** **P0. The deployment answer does not exist.**

Requirement. Deliverable 5: half a page on where the run lives, for the customer. Security and data governance: data stays in NovaMark's account, where inference happens, who can invoke the runtime.

Done in `docs/deployment.md`. The diagram is on the page. The agent, Bedrock, and the S3 snapshots are in their account. Access is SigV4 under one runtime role.

**[DONE]** **P0. The CFO brief does not exist.**

Requirement. Deliverable 6, using the five figures in "Success metrics": memo time from 4–6 hours to under 45 minutes, gathering time from about 65% to under 20%, compliance from 2–3 days to the same day, audit coverage from none to complete, consistency from 58% to above 90%. One page, for the CFO.

Done in `docs/cfo-brief.md`. Audit coverage is stated for the two demo memos: each review and the finished memo are saved, with the figure, the sentence it came from, and who approved it. The other four figures are marked not measured, with a reason.

**P0. The questions for David Chen do not exist.**

Requirement. Deliverable 7: five questions to David Chen before building, and three objections from NovaMark with an answer to each.

Now. Nothing in `docs/` is that note.

Fix. Add `docs/discovery.md`. Five questions. Three objections, each with an answer.

**[DONE]** **P0. The architecture must say how the research server is reached, and the picture must match the code.**

Requirement. Deliverable 3: how the MCP tool becomes a platform integration. Component 4: the knowledge base returns what the firm wrote, or a gap, and the run continues.

Done in `docs/architecture.md` and `docs/img/deployment.svg`. The current path is the in-process market mock and the research server over stdio. Gateway is described as not built and is not on the diagram. NovaMark's market system, research database, and ESG provider are stated as not connected.

**[DONE]** **P0. The requirements and the code disagree on who calls the model.**

Requirement. Process flow names which processes call the model.

Done in `docs/requirements.md`. It names `document_analyser`, `risk_assessor`, and `synthesis`. The risk level is computed in code.
