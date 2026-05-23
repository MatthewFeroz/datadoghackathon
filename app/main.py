from fastapi import Depends, FastAPI

from app.agent import run_agent
from app.payments import require_payment
from app.state import RunRequest, RunResponse

app = FastAPI(title="Docs Gap Agent", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/runs", response_model=RunResponse, dependencies=[Depends(require_payment)])
async def create_run(request: RunRequest) -> RunResponse:
    state = await run_agent(request)
    return RunResponse(
        run_id=state.run_id,
        status="completed" if not state.errors else "completed_with_errors",
        repo=state.repo,
        dry_run=state.dry_run,
        issues_scraped=len(state.issues),
        clusters_found=len(state.clusters),
        top_gaps=state.clusters,
        errors=state.errors,
    )
