# Deployment

NovaMark will not let customer data leave their own cloud. This prototype runs there.

The agent, the saved state, and the model call are in NovaMark's AWS account, in the region the stack is deployed to (this build uses us-west-2). A request arrives at AgentCore Runtime. The runtime calls Amazon Bedrock for the model. Each pause and the finished memo are written to an S3 bucket in that same account. Nothing in the path is an Anthropic, OpenAI, or other third-party API.

The market quote and the prior research in a demo memo are not NovaMark's systems. Both are the case-study mocks, running inside the agent. The filings are files in the deployment package.

Two things break in their account and do not break on a laptop.

The model id is a US inference profile. Bedrock may send that prompt to another US region. A local call has no residency check that fails, so the same run on a laptop does not reveal the hop.

The research client starts a subprocess on the same machine and talks to it over standard input. NovaMark's research server is not on that machine, and this build has no AgentCore Gateway in front of it, so the call that works locally has nowhere to go in their account until a server is reachable.
