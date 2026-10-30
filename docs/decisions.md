# Decisions

Four forks that shaped the build. The requirements ask for three; the fourth (how much the model decides) is an addition. Decisions 1 to 3 are the required ones.

## 1. Where inference and state live

**Problem.** A memo carries filing text, live quotes, and the firm's own research. NovaMark will not let customer data leave their cloud.

**A.** Bedrock in their account, with state in a KMS-encrypted S3 bucket in the same account ([deploy.py](../src/deploy.py)).
**B.** Anthropic, OpenAI, or OpenRouter directly. Faster to wire, no IAM work.

**Decision: A.** B sends customer data to a third party, which the deployment constraint rules out. Two caveats: the `us.` inference profile can route across US regions, and the runtime role currently allows `bedrock:InvokeModel` on all resources. Scoping it to one profile is planned ([code-reviews.md](code-reviews.md)).

## 2. How the run survives two multi-hour pauses

**Problem.** The run stops twice for a person who may take hours, and the whole run must be auditable, not only the final memo.

**A.** A flat sequence of processes over one typed value, with a `status` naming the next one, and each save a new numbered object ([orchestrator.py](../src/novamark/orchestrator.py), [state.py](../src/novamark/state.py)).
**B.** A graph with conditional edges and interrupt points ([Strands](https://strandsagents.com/) `Graph`), or an event-sourced engine.

**Decision: A.** A graph keeps its own execution state, so the audit trail would be derived from framework internals. Here the saved objects are the trail, and the state a reviewer approved still exists unchanged.

## 3. Where the two approvals happen

**Problem.** Two people sign off, hours apart. A separate approval tool would hold a second record of the same memo.

**A.** Inside the run: it saves and returns a packet, the decision arrives as a later call, and a wrong role is refused before anything is recorded ([gates.py](../src/novamark/process/gates.py)).
**B.** An approval UI with its own queue and database, or a Slack or email link.

**Decision: A.** One store holds both the memo and who approved it, so the two cannot disagree. B is only as strong as the tool. Limits of A today: roles are taken from the request, and the requester is not blocked from approving their own memo. Both are planned.

## 4. How much the model is allowed to decide

**Problem.** Consistency must rise from 58% to above 90%, so the same ticker has to produce the same evidence on every run.

**A.** Three fixed model jobs (extract, list risk reasons, write the memo). Fetching is code, and the risk level is computed by rule in [risk_assessor.py](../src/novamark/process/risk_assessor.py).
**B.** An agent per source that chooses its own tools, with the model scoring risk.

**Decision: A.** B lets the evidence path vary between runs. A makes the gate rule deterministic for a given set of values, and compliance can change the 0.75 threshold in [model.py](../src/novamark/model.py) without touching a prompt.
