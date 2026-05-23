from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from os import getenv
from time import perf_counter
from typing import Any

from app import events

try:
    from ddtrace import tracer
except Exception:  # pragma: no cover - optional dependency
    tracer = None


def tracing_enabled() -> bool:
    return tracer is not None


def _service_name() -> str:
    return getenv("DD_SERVICE", "docs-gap-agent")


_TOOL_TO_SPONSOR = {
    "research_repo": "github",
    "cluster_issues": "openai",
    "store_results": "clickhouse",
    "publish_citeable": "senso",
    "search_official_docs": "nimble",
    "nimble_search": "nimble",
}


@contextmanager
def traced_tool(name: str, run_id: str, repo: str):
    start = perf_counter()
    traced = tracing_enabled()
    events.publish(
        run_id,
        {
            "type": "tool_start",
            "name": name,
            "sponsor": _TOOL_TO_SPONSOR.get(name),
            "repo": repo,
            "traced": traced,
        },
    )

    status = "ok"
    error_msg: str | None = None
    span_cm = (
        tracer.trace(f"tool.{name}", service=_service_name())
        if tracer
        else nullcontext(None)
    )

    with span_cm as span:
        if span is not None:
            span.set_tag("agent.run_id", run_id)
            span.set_tag("github.repo", repo)
            span.set_tag("tool.name", name)

        try:
            yield span
        except Exception as exc:
            status = "error"
            error_msg = str(exc)
            if span is not None:
                span.set_tag("error", True)
                span.set_tag("error.msg", error_msg)
            raise
        finally:
            duration_ms = (perf_counter() - start) * 1000
            if span is not None:
                span.set_tag("status", status)
                span.set_metric("duration_ms", duration_ms)
            events.publish(
                run_id,
                {
                    "type": "tool_end",
                    "name": name,
                    "sponsor": _TOOL_TO_SPONSOR.get(name),
                    "status": status,
                    "duration_ms": round(duration_ms, 1),
                    "error": error_msg,
                    "traced": traced,
                },
            )


@contextmanager
def traced_run(run_id: str, repo: str):
    """Parent span for a full agent run."""
    span_cm = (
        tracer.trace("agent.run", service=_service_name(), resource=repo)
        if tracer
        else nullcontext(None)
    )
    with span_cm as span:
        if span is not None:
            span.set_tag("agent.run_id", run_id)
            span.set_tag("github.repo", repo)
        yield span


async def run_traced(
    name: str,
    run_id: str,
    repo: str,
    fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    with traced_tool(name, run_id, repo):
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            return await result
        return result
