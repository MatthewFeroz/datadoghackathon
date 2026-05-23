from app.state import AgentState, RunRequest
from app.tools.clickhouse import store_run
from app.tools.cluster import cluster_issues
from app.tools.github import research_repo
from app.tracing import run_traced


async def run_agent(request: RunRequest) -> AgentState:
    state = AgentState(repo=request.repo, dry_run=request.dry_run)

    while True:
        action = decide_next_action(state)
        state.next_action = action

        if action == "research_repo":
            try:
                state.issues = await run_traced(
                    "research_repo",
                    state.run_id,
                    state.repo,
                    research_repo,
                    state.repo,
                    request.limit,
                )
            except Exception as exc:
                state.errors.append(str(exc))
                break
            continue

        if action == "cluster_issues":
            try:
                state.clusters = await run_traced(
                    "cluster_issues",
                    state.run_id,
                    state.repo,
                    cluster_issues,
                    state.issues,
                )
            except Exception as exc:
                state.errors.append(str(exc))
            continue

        if action == "store_results":
            try:
                await run_traced(
                    "store_results",
                    state.run_id,
                    state.repo,
                    store_run,
                    state,
                )
            except Exception as exc:
                state.errors.append(f"ClickHouse store failed: {exc}")
            break

        break

    return state


def decide_next_action(state: AgentState) -> str:
    if not state.issues and not state.errors:
        return "research_repo"
    if state.issues and not state.clusters:
        return "cluster_issues"
    return "store_results"
