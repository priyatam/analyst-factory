"""In-process AWS Distro for OpenTelemetry, and one span helper.

The runtime launches `python novamark/agent.py`, so `start` runs in that process.
It does not build a second tracer provider: Strands already calls
`trace.get_tracer_provider()`, and replacing it would drop the distro's exporter.
Local runs and tests leave `STATE_BUCKET` unset, so `start` returns immediately.

`span` opens one span when the caller enters it. The tracer is taken then, so a
test provider installed earlier is used. Attributes are only str, bool, int, or
float: the prompt text does not belong on a span.
"""
import os
from collections.abc import Iterator
from contextlib import contextmanager

# Libraries this process never imports. Logging stays enabled so agent logs export.
_SKIP = ",".join((
    "django", "flask", "fastapi", "starlette",
    "grpc_aio_client", "grpc_aio_server", "grpc_client", "grpc_server",
    "kafka", "aiokafka", "confluent_kafka",
    "redis", "pymemcache",
    "sqlalchemy", "psycopg2", "pymysql", "sqlite3", "aiopg", "asyncpg",
    "mysql", "mysqlclient", "tortoiseorm",
    "httpx", "httpx2", "requests", "urllib", "urllib3", "aiohttp-client", "aio-pika",
    "botocore", "boto3", "aiobotocore",
    "celery", "pika", "pymongo", "cassandra", "tornado", "pyramid", "falcon",
    "jinja2", "system_metrics", "threading", "remoulade", "aws-lambda",
))

_started = False
_TYPES = (str, bool, int, float)


@contextmanager
def span(name: str, **attributes: str | bool | int | float) -> Iterator[None]:
    """Open a span named `name` with the given attributes."""
    from opentelemetry import trace

    for key, value in attributes.items():
        if not isinstance(value, _TYPES):
            raise TypeError(f"{key} must be str, bool, int, or float")
    with trace.get_tracer("novamark").start_as_current_span(name, attributes=attributes):
        yield


def start() -> None:
    """Turn on ADOT when the runtime flag is set, or this process is the runtime."""
    global _started
    if _started:
        return
    enabled = os.environ.get("AGENT_OBSERVABILITY_ENABLED", "").lower() == "true"
    if not enabled and not os.environ.get("STATE_BUCKET"):
        return
    _started = True
    os.environ.setdefault("AGENT_OBSERVABILITY_ENABLED", "true")
    os.environ.setdefault("OTEL_PYTHON_DISTRO", "aws_distro")
    os.environ.setdefault("OTEL_PYTHON_CONFIGURATOR", "aws_configurator")
    os.environ.setdefault("OTEL_SERVICE_NAME", "novamark")
    os.environ.setdefault("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", _SKIP)
    from opentelemetry.instrumentation.auto_instrumentation import initialize

    initialize(swallow_exceptions=False)


def flush() -> None:
    """Force-flush traces and logs before the microVM freezes."""
    from opentelemetry import trace
    from opentelemetry._logs import get_logger_provider

    force_traces = getattr(trace.get_tracer_provider(), "force_flush", None)
    if force_traces is not None:
        force_traces()
    force_logs = getattr(get_logger_provider(), "force_flush", None)
    if force_logs is not None:
        force_logs()
