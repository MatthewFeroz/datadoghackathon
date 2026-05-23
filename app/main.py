import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from app import events
from app.agent import run_agent
from app.payments import (
    create_checkout_session,
    format_dollars,
    price_for_severity,
    verify_checkout_session,
)
from app.render import render_events
from app.state import RUNS, AgentState, RunRequest, RunResponse
from app.tools.senso import publish_citeable
from app.config import get_settings

WEB_DIR = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
templates.env.globals["gitshell_icon"] = "/static/logos/gitshell-icon.svg"
templates.env.globals["gitshell_logo"] = "/static/logos/gitshell.svg"

app = FastAPI(title="Git Shell", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


def _gap_context(state: AgentState, index: int) -> dict:
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")
    cluster = state.clusters[index]
    amount_cents = cluster.payment_amount_cents or price_for_severity(cluster.severity)
    source_issues = [
        issue for issue in state.issues if issue.number in set(cluster.issue_numbers)
    ]
    return {
        "run_id": state.run_id,
        "repo": state.repo,
        "index": index,
        "cluster": cluster,
        "amount_cents": amount_cents,
        "amount_label": format_dollars(amount_cents),
        "source_issues": source_issues,
    }


def _all_finding_contexts() -> list[dict]:
    findings: list[dict] = []
    for state in RUNS.values():
        for index, _cluster in enumerate(state.clusters):
            findings.append(_gap_context(state, index))
    return findings


def _monetization_context() -> dict[str, str | bool | int]:
    settings = get_settings()
    return {
        "stripe_configured": bool(settings.stripe_secret_key),
        "dev_payment_bypass": settings.dev_payment_bypass,
        "currency": settings.stripe_currency.upper(),
        "low_price": format_dollars(settings.stripe_low_severity_cents),
        "medium_price": format_dollars(settings.stripe_medium_severity_cents),
        "high_price": format_dollars(settings.stripe_high_severity_cents),
        "dashboard_url": "https://dashboard.stripe.com/test/payments",
    }


@app.get("/health")
async def health() -> dict[str, str | bool]:
    from app.tracing import tracing_enabled

    return {"status": "ok", "datadog_tracing": tracing_enabled()}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"default_repo": "DataDog/dd-trace-py"},
    )


@app.get("/findings", response_class=HTMLResponse)
async def findings_index(request: Request) -> HTMLResponse:
    findings = _all_finding_contexts()
    findings.sort(
        key=lambda item: (item["cluster"].published_url is not None, item["run_id"]),
        reverse=True,
    )
    return templates.TemplateResponse(
        request,
        "findings.html",
        {"findings": findings, "finding_count": len(findings)},
    )


@app.get("/monetization", response_class=HTMLResponse)
async def monetization_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "monetization.html",
        _monetization_context(),
    )


@app.post("/runs")
async def create_run_api(request: RunRequest) -> dict[str, str]:
    state = AgentState(repo=request.repo, dry_run=request.dry_run)
    RUNS[state.run_id] = state
    asyncio.create_task(run_agent(request, state=state))
    return {"run_id": state.run_id}


@app.post("/web/runs", response_class=HTMLResponse)
async def create_run_web(
    request: Request,
    repo: str = Form(...),
    docs_url: str | None = Form("https://ddtrace.readthedocs.io/"),
    limit: int = Form(50),
) -> HTMLResponse:
    run_request = RunRequest(
        repo=repo,
        docs_url=docs_url,
        limit=limit,
        dry_run=False,
    )
    state = AgentState(repo=run_request.repo, dry_run=run_request.dry_run)
    RUNS[state.run_id] = state
    asyncio.create_task(run_agent(run_request, state=state))
    return templates.TemplateResponse(
        request,
        "_partials/run_panel.html",
        {"run_id": state.run_id, "repo": state.repo},
    )


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str) -> RunResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse(
        run_id=state.run_id,
        status=state.status,
        repo=state.repo,
        dry_run=state.dry_run,
        issues_scraped=len(state.issues),
        clusters_found=len(state.clusters),
        docs_sources=state.docs_sources,
        top_gaps=state.clusters,
        decisions=state.decisions,
        errors=state.errors,
    )


@app.get("/runs/{run_id}/gaps/{index}", response_class=HTMLResponse)
async def finding_page(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request,
        "finding.html",
        _gap_context(state, index),
    )


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str) -> EventSourceResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in events.subscribe(run_id):
            for sse_event in render_events(event, templates, run_id):
                yield sse_event

    return EventSourceResponse(event_generator())


async def _publish_gap(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    cluster = state.clusters[index]
    if cluster.review_status != "approved":
        raise HTTPException(status_code=409, detail="Approve the Senso document before publishing.")
    publish_result = await publish_citeable(
        run_id=run_id,
        repo=state.repo,
        cluster=cluster,
        dry_run=state.dry_run,
    )
    url = publish_result.get("url") or ""
    cluster.published_url = url
    cluster.review_status = "published" if url else "approved"
    cluster.senso_content_id = publish_result.get("content_id")
    cluster.senso_version_id = publish_result.get("version_id")
    if not url:
        return templates.TemplateResponse(
            request,
            "_partials/publish_preview.html",
            {"reason": publish_result.get("reason") or "No public Cited.md URL was created."},
        )
    events.publish(
        run_id,
        {
            "type": "gap_published",
            "index": index,
            "url": url,
            "sponsor": "senso",
        },
    )
    return templates.TemplateResponse(
        request,
        "_partials/finding_actions.html",
        _gap_context(state, index),
    )


@app.post("/runs/{run_id}/gaps/{index}/checkout")
async def create_gap_checkout(run_id: str, index: int) -> Response:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    cluster = state.clusters[index]
    checkout_url = create_checkout_session(
        run_id=run_id,
        gap_index=index,
        title=cluster.draft_title or cluster.name,
        severity=cluster.severity,
    )
    return Response(status_code=204, headers={"HX-Redirect": checkout_url})


@app.post("/runs/{run_id}/gaps/{index}/approve", response_class=HTMLResponse)
async def approve_gap(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    cluster = state.clusters[index]
    cluster.review_status = "approved"
    events.publish(
        run_id,
        {
            "type": "gap_approved",
            "index": index,
            "title": cluster.draft_title or cluster.name,
        },
    )
    return templates.TemplateResponse(
        request,
        "_partials/finding_actions.html",
        _gap_context(state, index),
    )


@app.get("/payments/success", response_class=HTMLResponse)
async def payment_success(request: Request, session_id: str) -> HTMLResponse:
    receipt, run_id, index = verify_checkout_session(session_id)
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    cluster = state.clusters[index]
    cluster.payment_status = "paid"
    cluster.payment_amount_cents = receipt.amount_cents
    cluster.payment_id = receipt.payment_id
    cluster.review_status = "approved"
    events.publish(
        run_id,
        {
            "type": "payment_received",
            "index": index,
            "amount_cents": receipt.amount_cents,
            "payment_id": receipt.payment_id,
        },
    )
    publish_response = await _publish_gap(request, run_id, index)
    return templates.TemplateResponse(
        request,
        "_partials/payment_success.html",
        {
            "run_id": run_id,
            "index": index,
            "cluster": cluster,
            "amount_cents": receipt.amount_cents,
            "amount_label": format_dollars(receipt.amount_cents),
            "payment_id": receipt.payment_id,
            "publish_html": publish_response.body.decode(),
        },
    )


@app.post("/runs/{run_id}/gaps/{index}/publish", response_class=HTMLResponse)
async def publish_gap(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    return await _publish_gap(request, run_id, index)


@app.post("/runs/{run_id}/gaps/{index}/reject", response_class=HTMLResponse)
async def reject_gap(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    state.clusters[index].review_status = "rejected"
    events.publish(
        run_id,
        {"type": "gap_rejected", "index": index},
    )
    return templates.TemplateResponse(
        request,
        "_partials/rejected.html",
        {},
    )


@app.post("/runs/{run_id}/api/gaps/{index}/publish")
async def publish_gap_json(run_id: str, index: int) -> dict[str, str]:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")
    cluster = state.clusters[index]
    if cluster.review_status != "approved":
        raise HTTPException(status_code=409, detail="Approve the Senso document before publishing.")
    publish_result = await publish_citeable(
        run_id=run_id,
        repo=state.repo,
        cluster=cluster,
        dry_run=state.dry_run,
    )
    url = publish_result.get("url") or ""
    cluster.published_url = url
    cluster.review_status = "published" if url else "approved"
    cluster.senso_content_id = publish_result.get("content_id")
    cluster.senso_version_id = publish_result.get("version_id")
    return {"url": url, "status": publish_result.get("status") or "unknown"}


@app.get("/runs/{run_id}/events.json")
async def stream_events_json(run_id: str) -> EventSourceResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in events.subscribe(run_id):
            yield {"event": event["type"], "data": json.dumps(event)}

    return EventSourceResponse(event_generator())
