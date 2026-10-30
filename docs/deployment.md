# Deployment

![NovaMark research workforce: deployment](img/deployment.svg)

The stack is one CDK app, `src/deploy.py`. From the repo root, after a one-time `npx aws-cdk bootstrap` for the account and Region:

```sh
npx aws-cdk deploy
```

CDK packages the agent as a linux/arm64 Python 3.12 zip and creates the state bucket, the runtime role, and the AgentCore Runtime. Run the same command again and CloudFormation changes only what differs. No second script, and no secret, password, or API key in the repo or the template.

The picture shows one AgentCore Runtime session in NovaMark's AWS account, with Amazon Bedrock, S3, and CloudWatch in that account, and the market system, the research database, and the ESG provider beside it and not called.

The agent, the saved state, and the model call run in NovaMark's AWS account, in the region the stack is deployed to (this build uses us-west-2). Inference is Amazon Bedrock in that account. A prompt and its answer stay there: nothing is sent to Anthropic, OpenAI, or any other third-party model API. State is an S3 bucket in the same account, KMS-encrypted, TLS-only, and private. Each pause and the finished memo are snapshots in that bucket.

A request is signed with AWS Signature Version 4. Only an IAM principal allowed to invoke the runtime can start a run or send a decision, and there is no separate password or API key. The memo is produced by one IAM role the runtime service assumes. The model has no credentials and no tools. The reviewer name and role are fields in the request and are not yet tied to the signing principal, and the runtime role can call any Bedrock model and delete objects in the bucket.

Demo market quotes and prior research are case-study mocks inside the agent, not NovaMark's live market system, research database, or ESG provider. Filings in the demo are files in the package.
