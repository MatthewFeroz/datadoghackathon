from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.state import GapCluster, Issue
from app.tools.clickhouse import store_run
from app.tools.cluster import cluster_issues
from app.tools.github import research_repo
from app.tracing import run_traced


class DocsGapGraphState(TypedDict, total=False):
    run_id: str
    repo: str
    limit: int
    dry_run: bool
    issues: list[dict]
    clusters: list[dict]
    errors: list[str]
    next_action: str
    researched: bool
    analyzed: bool
    stored: bool


async def observe(state: DocsGapGraphState) -> DocsGapGraphState:
    if not state.get("researched") and not state.get("errors"):
        state["next_action"] = "research"
    elif state.get("issues") and not state.get("analyzed"):
        state["next_action"] = "analyze"
    else:
        state["next_action"] = "store"
    return state


def route(
    state: DocsGapGraphState,
) -> Literal["research", "analyze", "store"]:
    return state["next_action"]  # type: ignore[return-value]


async def research(state: DocsGapGraphState) -> DocsGapGraphState:
    try:
        issues = await run_traced(
            "research_repo",
            state["run_id"],
            state["repo"],
            research_repo,
            state["repo"],
            state.get("limit", 50),
        )
        state["issues"] = [issue.model_dump(mode="json") for issue in issues]
    except Exception as exc:
        state.setdefault("errors", []).append(str(exc))
    finally:
        state["researched"] = True
    return state


async def analyze(state: DocsGapGraphState) -> DocsGapGraphState:
    try:
        issues = [Issue.model_validate(issue) for issue in state.get("issues", [])]
        clusters = await run_traced(
            "cluster_issues",
            state["run_id"],
            state["repo"],
            cluster_issues,
            issues,
        )
        state["clusters"] = [cluster.model_dump(mode="json") for cluster in clusters]
    except Exception as exc:
        state.setdefault("errors", []).append(str(exc))
    finally:
        state["analyzed"] = True
    return state


async def store(state: DocsGapGraphState) -> DocsGapGraphState:
    from app.state import AgentState

    agent_state = AgentState(
        run_id=state["run_id"],
        repo=state["repo"],
        dry_run=state.get("dry_run", True),
        issues=[Issue.model_validate(issue) for issue in state.get("issues", [])],
        clusters=[
            GapCluster.model_validate(cluster) for cluster in state.get("clusters", [])
        ],
        errors=state.get("errors", []),
    )
    try:
        await run_traced(
            "store_results",
            state["run_id"],
            state["repo"],
            store_run,
            agent_state,
        )
    except Exception as exc:
        state.setdefault("errors", []).append(f"ClickHouse store failed: {exc}")
    finally:
        state["stored"] = True
    return state


builder = StateGraph(DocsGapGraphState)
builder.add_node("observe", observe)
builder.add_node("research", research)
builder.add_node("analyze", analyze)
builder.add_node("store", store)

builder.set_entry_point("observe")
builder.add_conditional_edges(
    "observe",
    route,
    {
        "research": "research",
        "analyze": "analyze",
        "store": "store",
    },
)
builder.add_edge("research", "observe")
builder.add_edge("analyze", "observe")
builder.add_edge("store", END)

graph = builder.compile()
