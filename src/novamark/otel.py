"""In-process AWS Distro for OpenTelemetry, and one span helper.

The runtime launches `python novamark/agent.py`, so `start` runs in that process.
It does not build a second tracer provider: Strands already calls
`trace.get_tracer_provider()`, and replacing it would drop the distro's exporter.
Instrumentation is FastAPI, Lambda, botocore, and logging. Local runs and tests
leave `STATE_BUCKET` unset, so `start` returns immediately.

`span` opens one span when the caller enters it. The tracer is taken then, so a
test provider installed earlier is used. Attributes are only str, bool, int, or
float: the prompt text does not belong on a span.
"""
import os
from collections.abc import Iterator
from contextlib import contextmanager

# The install only carries FastAPI, Lambda, botocore, and logging. These distro
# instrumentors ship inside aws-opentelemetry-distro and are not used here.
_SKIP = "aws_crewai,aws_langchain,aws_llama-index,aws_openai_agents"

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
