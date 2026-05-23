from collections.abc import Callable
from contextlib import contextmanager
from time import perf_counter
from typing import Any

try:
    from ddtrace import tracer
except Exception:  # pragma: no cover - optional dependency
    tracer = None


@contextmanager
def traced_tool(name: str, run_id: str, repo: str):
    start = perf_counter()
    if tracer is None:
        yield None
        return

    span = tracer.trace(f"tool.{name}", service="docs-gap-agent")
    span.set_tag("agent.run_id", run_id)
    span.set_tag("github.repo", repo)
    try:
        yield span
        span.set_tag("status", "ok")
    except Exception as exc:
        span.set_tag("status", "error")
        span.set_tag("error.msg", str(exc))
        raise
    finally:
        span.set_metric("duration_ms", (perf_counter() - start) * 1000)
        span.finish()


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
