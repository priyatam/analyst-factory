"""CDK app: state bucket, audit table, runtime role, and an AgentCore Runtime from a code zip
(linux/arm64, Python 3.12, no container). Synths when CDK_OUTDIR is set; otherwise enables
CloudWatch Transaction Search (idempotent) and deploys. Never run unless asked."""
import os
import shutil
import subprocess
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as agentcore, aws_iam as iam, aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as assets

from novamark import model

BUILD = Path("build/package")


def prune(pkg: Path) -> None:
    """Drop what the runtime never imports, to cut cold-start extraction time.

    `botocore` ships a JSON model for all 439 AWS services (23 MB); this run speaks only S3,
    Bedrock Runtime, STS, and CloudWatch Logs (the EMF exporter). Those models are pure
    cold-start cost, extracted from the zip on every new microVM, which is what pushes
    initialization past the 30s budget.
    """
    keep = {"s3", "bedrock-runtime", "sts", "bedrock-agentcore", "bedrock-agentcore-control",
            "logs", "_retry", "endpoints"}
    data = pkg / "botocore" / "data"
    if data.exists():
        for service in data.iterdir():
            if service.name not in keep:
                shutil.rmtree(service, ignore_errors=True)

    for path in list(pkg.glob("**/__pycache__")) + list(pkg.glob("**/tests")):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for record in pkg.glob("**/*.dist-info/RECORD"):
        record.unlink(missing_ok=True)


def package() -> Path:
    """Install dependencies for the runtime platform, copy the data, then prune."""
    shutil.rmtree(BUILD, ignore_errors=True)
    subprocess.run(["uv", "pip", "install", "--target", str(BUILD), "--python-platform", "aarch64-manylinux2014",
                    "--python-version", "3.12", "--no-compile", "."], check=True)
    shutil.copytree("src/data", BUILD / "data")
    shutil.copytree("src/mocks", BUILD / "mocks")
    prune(BUILD)
    return BUILD


def add_stack(app: cdk.App, package_dir: str) -> cdk.Stack:
    # Pinned, so `Stack.of(stack).region` is a literal in the environment variables rather than
    # a deploy-time token. The runtime reads AWS_REGION to build its boto3 and Bedrock clients, so
    # a mismatch sends storage and inference to the wrong region.
    region = os.getenv("CDK_DEFAULT_REGION") or os.getenv("AWS_REGION") or model.REGION
    stack = cdk.Stack(app, "NovaMark", env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT") or os.getenv("AWS_ACCOUNT_ID"),
        region=region))
    state = s3.Bucket(stack, "State", encryption=s3.BucketEncryption.KMS_MANAGED, enforce_ssl=True,
                      block_public_access=s3.BlockPublicAccess.BLOCK_ALL)
    code = assets.Asset(stack, "Code", path=package_dir)

    role = iam.Role(stack, "RuntimeRole", assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"))
    role.add_to_policy(iam.PolicyStatement(
        actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources=["*"]))  # TODO: pin to the inference profile for model.MODEL_ID
    state.grant_read_write(role)
    code.grant_read(role)
    # Without these the runtime cannot create its log group, and a failure inside it is a bare
    # 500 with nothing to read. The architecture promises CloudWatch, so the role has to allow it.
    role.add_to_policy(iam.PolicyStatement(
        actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        resources=[f"arn:aws:logs:{region}:*:log-group:/aws/bedrock-agentcore/runtimes/*"]))
    logs.LogGroup(stack, "AgentLogs", log_group_name="/novamark/agent").grant_write(role)
    role.add_to_policy(iam.PolicyStatement(
        actions=["logs:PutResourcePolicy", "logs:DescribeResourcePolicies"],
        resources=["*"]))
    role.add_to_policy(iam.PolicyStatement(
        actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords",
                 "xray:GetSamplingRules", "xray:GetSamplingTargets"],
        resources=["*"]))
    role.add_to_policy(iam.PolicyStatement(
        actions=["cloudwatch:PutMetricData"],
        resources=["*"],
        conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}}))
    runtime = agentcore.CfnRuntime(
        stack, "Runtime", agent_runtime_name="novamark_research", role_arn=role.role_arn,
        network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(network_mode="PUBLIC"),
        agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
            code_configuration=agentcore.CfnRuntime.CodeConfigurationProperty(
                runtime="PYTHON_3_12", entry_point=["novamark/agent.py"],
                code=agentcore.CfnRuntime.CodeProperty(s3=agentcore.CfnRuntime.S3LocationProperty(
                    bucket=code.s3_bucket_name, prefix=code.s3_object_key)))),
        environment_variables={
            "STATE_BUCKET": state.bucket_name,
            "AWS_REGION": cdk.Stack.of(stack).region,
            "AWS_GENAI_CONTENT_EXTRACTION_OPT_OUT": "true",
            "UNIFIED_TRACES_DESTINATION_ENABLED": "true",
            "OTEL_SERVICE_NAME": "novamark",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS":
                "x-aws-log-group=/novamark/agent,x-aws-log-stream=runtime-logs,"
                "x-aws-metric-namespace=bedrock-agentcore",
        },
    )
    cdk.CfnOutput(stack, "RuntimeArn", value=runtime.attr_agent_runtime_arn,
                  description="export NOVAMARK_RUNTIME_ARN=<this value>")
    return stack


def enable_transaction_search() -> None:
    import boto3
    client = boto3.client("xray", region_name=os.getenv("CDK_DEFAULT_REGION", model.REGION))
    try:
        client.update_trace_segment_destination(Destination="CloudWatchLogs")
    except client.exceptions.InvalidRequestException as error:
        if "already set" not in str(error):
            raise


if __name__ == "__main__":
    synth_only = bool(os.getenv("CDK_OUTDIR"))
    if not synth_only:
        enable_transaction_search()
    app = cdk.App()
    add_stack(app, str(package()))
    app.synth()
