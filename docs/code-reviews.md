# Code reviews

Findings from an architecture review of the proof of concept (POC) against the requirements and
the AWS Well-Architected pillars. The bar is a minimal, demonstrable POC with least-privilege
Identity and Access Management (IAM), not production hardening.

## Well-Architected view

- **Security.** The biggest gap.
  - The runtime role allows `bedrock:InvokeModel` on every resource and can delete from the state bucket.
  - The role's trust policy has no source account or source ARN condition.
  - Reviewer roles come from the request body, so any caller allowed to invoke can claim any role.
  - The `us.` inference profile may route across US regions, which the deployment answer must state.
- **Reliability.** The snapshot sequence is the object count, so concurrent saves collide and a retried decision can fail instead of being a no-op. There is no model retry. Both are acceptable for a POC if documented.
- **Operational excellence.** `deploy.py` changes account-wide trace settings on every deploy.
- **Cost and performance.** Three model calls per run and a pruned botocore are fine. Leave them.

## Three refactors for the first commit

1. **Make the gates do what the docs claim.**
   - `gates.decide` must check that `decision["gate"]` equals the run's `status`.
   - Record `requested_by` at intake and refuse self-approval.
   - Read roles through one `caller_roles(payload)` function, documented as a trusted-caller stand-in.
   - Compute the snapshot sequence in one place for both local and S3 stores.
2. **Make the deployed runtime reach its edges.**
   - The deployed runtime uses the mock market app in process and a mock knowledge base subprocess, so its data is mock data.
   - Add one `deps_for(mode)` factory shared by `agent.py`, the demo, and tests, with the in-process mocks used on AWS and labelled as mocks.
   - Describe AgentCore Gateway as the next step, not as built.
   - Make `quote_once` truly async so the fan-out runs concurrently.
3. **Least-privilege IAM in** `deploy.py`**.**
   - Scope model access to the inference-profile and foundation-model ARNs, with the `bedrock:InferenceProfileArn` condition.
   - Scope the state bucket to `PutObject` and `GetObject` on `runs/*` and `ListBucket` on that prefix, with no delete, plus versioning, so the audit log is append-only in IAM.
   - Add `aws:SourceAccount` and `aws:SourceArn` to the trust policy.
   - Add the logs, trace, and workload-identity permissions the runtime needs, checked against the AgentCore execution-role documentation.
   - Make Transaction Search opt-in.
   - Read the runtime ARN from an environment variable, and delete `diag.py` and `repro.py`.

## End state the diagrams show and the code does not do yet

- **Telemetry spans.** The execution diagram shows a span per transition and per model call going to CloudWatch. Today the code emits only Python logs, plus a traceback when `invoke` fails, and `deploy.py` switches on Transaction Search without anything feeding it spans. To build it, add `aws-opentelemetry-distro` and start the entrypoint under auto-instrumentation, wrap each pass of `advance` in a span carrying `run_id`, `status` and `revision`, and turn on the Strands trace attributes for the model call. Then check the spans appear in the runtime's log group.
- **Verified reviewer identity.** The identity diagram marks `reviewer` and `roles` as claimed. The fix is the `caller_roles(payload)` change in refactor 1, then reading identity from the verified principal.
- **AgentCore Gateway.** The deployment diagram shows it. It is not built.

## Questions about the `values` schema

- **The entry is an untyped `dict`.** `values: dict[str, dict]` documents nothing, and a misspelt key passes the type checker. A `TypedDict` for the entry would name the fields without adding a class or a new concept.
- **A reviewer's amendment replaces the whole entry and skips the evidence check.** `gates._stamp` swaps in whatever the reviewer sent, so the entry loses `excerpt` and `source_id` unless they supply them, and `evidence_check` does not run again. Decide whether a human value needs a citation, and who is recorded on the entry (today only on `decisions`).
- **There is no period or unit.** `revenue` has no fiscal year, and `value` carries no unit or scale, which is why the `$11,900` case needs a cap. A filing with two years of revenue has nowhere to put the second. Add `period` and `unit`, or key the metric by period.
- **Confidence is the model's own number.** It is only lowered by code for unscaled amounts and nulls, so the 0.75 floor rests on an uncalibrated score. Check it against a labelled sample before relying on it.
- **One excerpt per metric.** A figure the model derives from two sentences has no single citation.
