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

**P2. A throttled model call stops the run.** A Bedrock 429 is not retried.

Done when `model.ask` backs off and retries, or the architecture states that a throttled call fails the run.

## Operational excellence

**P1. One way to build dependencies.** `agent.py`, the demo, and the tests each wire the market client and the knowledge base. The deployed runtime calls the mock market app in process and starts the mock knowledge base as a subprocess.

Done when those three call one factory. On AWS that factory uses the in-process mocks, and the code says they are mocks.

**P1. A deploy must not change the account.** `deploy.py` turns on Transaction Search for the whole account on every deploy.

Done when a deploy does not call that API unless asked. The demo reads the runtime ARN from the environment. `diag.py` and `repro.py` are gone.

**P2. Spans the execution diagram already draws.** The code emits Python logs. Nothing sends a span per transition or per model call.

Done when a published run shows a span for each pass of `advance`, carrying `run_id`, `status`, and `revision`, and a span for each model call, in the runtime log group.

**P2. AgentCore Gateway, if it stays on the diagram.** It is not built. Acceptance P0 already requires the docs to say so.

Done when the deployment diagram includes Gateway only if a request reaches the market API and the knowledge base through it.

## Performance

**P1. The market call blocks the event loop.** `quote_once` uses a blocking HTTP client, so the quote and prior research run one after the other.

Done when the quote fetch awaits. A slow knowledge base does not wait behind it. A 429 still honours `Retry-After` for at most three attempts.

## Cost

No change. Three model calls per run stay. Do not add a fourth to close a review comment.



## Acceptance criteria

NovaMark's written requirements in `docs/requirements.md`. Each item is the requirement, what the repo does instead, and the change.

**P0. Working code must show two finished memos.**

Requirement. Deliverable 1, and component 1: one clean run, and one run that stops for low confidence or high risk. Both go through the workers, the MCP read, both approvals, and end as a published memo.

Now. `README.md` ("What you see") runs AAPL and NVDA. AAPL is called the tidy filing, then rated high risk, and stops at `senior_review`. NVDA is flagged for the unscaled Gaming figure and stops at the same gate. Both are the risky path. There is no clean path.

Fix. Change `src/demo.py` and that README section. One ticker must have every confidence at or above 0.75 and a risk that is not high, so it skips `senior_review`, stops only for compliance, and prints `published`. The other ticker must enter `senior_review` for a confidence under 0.75 or a high risk, then compliance, then `published`.

**P0. The deployment answer does not exist.**

Requirement. Deliverable 5: half a page. Customer data stays in NovaMark's account. Where each part runs. Where inference happens. Two things that break in their account and do not break on the author's machine.

Now. `docs/decisions.md` decision 1 and `docs/architecture.md` ("Runtime") say inference is Bedrock in their account and state is in their bucket. Neither is the half page, and neither names two breaks that show up only in their account.

Fix. Add `docs/deployment.md`. State that the runtime, the bucket, and the model call are in their account, in their region. Name these two breaks. The `us.` inference profile can send a prompt to another US region; a local call has no residency control that fails. The knowledge-base client starts a subprocess on the same machine over stdio; their research server is not on that machine, and Gateway is not there to reach it.

**P0. The CFO brief does not exist.**

Requirement. Deliverable 6, using the five figures in "Success metrics": memo time from 4–6 hours to under 45 minutes, gathering time from about 65% to under 20%, compliance from 2–3 days to the same day, audit coverage from none to complete, consistency from 58% to above 90%. One page, for the CFO. Where they are, where this leaves them, how they would know it worked. No product list. No platform names.

Now. No such page. The README repeats the memo-time target and does not report a result for any of the five.

Fix. Add `docs/cfo-brief.md`. One page. For each of the five figures, give the result from the demo or write that this prototype did not measure it and why. Do not leave a figure as a target with no result and no reason.

**P0. The questions for David Chen do not exist.**

Requirement. Deliverable 7: five questions to David Chen before building, and three objections from NovaMark with an answer to each.

Now. Nothing in `docs/` is that note.

Fix. Add `docs/discovery.md`. Five questions. Three objections, each with an answer.

**P0. The architecture must say how the research server is reached, and the picture must match the code.**

Requirement. Deliverable 3: how the MCP tool becomes a platform integration. The introduction: the prototype connects to the systems the firm already runs. Component 4: the knowledge base returns what the firm wrote, or a gap, and the run continues.

Now. The code starts `mock_mcp_research_kb_server.py` over stdio and calls the market mock in process. `docs/architecture.md` ("Runtime") says Gateway is the intention and is not built. The deployment diagram still draws Gateway on the path a request takes.

Fix. Edit the deployment diagram so Gateway is not on the path this build uses. In `docs/architecture.md`, state the current path (stdio mock, in-process market mock) and the later path (HTTP behind Gateway, tenant taken from the verified identity, not from `params._meta.tenant_id`). Do not describe NovaMark's market system, research database, or ESG provider as connected.

**P0. The requirements and the code disagree on who calls the model.**

Requirement. Process flow: `document_analyser` and `synthesis` are the only processes that call the model.

Now. `risk_assessor.assess` also calls the model, for the risk reasons. The level is then computed in code. `docs/decisions.md` decision 4 records that third call. `docs/requirements.md` does not.

Fix. Change the process-flow sentence in `docs/requirements.md` so it lists that third call. Leave the code as decision 4 describes it.
