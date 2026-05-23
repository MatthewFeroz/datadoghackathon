from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


class RunRequest(BaseModel):
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    limit: int = Field(default=50, ge=1, le=100)
    dry_run: bool = True


class Issue(BaseModel):
    number: int
    title: str
    body: str | None = None
    url: HttpUrl
    state: str
    labels: list[str] = Field(default_factory=list)
    comments_count: int = 0
    created_at: datetime
    updated_at: datetime


class GapCluster(BaseModel):
    name: str
    summary: str
    recurring_question: str
    issue_numbers: list[int]
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)


class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    repo: str
    dry_run: bool = True
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    issues: list[Issue] = Field(default_factory=list)
    clusters: list[GapCluster] = Field(default_factory=list)
    next_action: str | None = None
    errors: list[str] = Field(default_factory=list)


class RunResponse(BaseModel):
    run_id: str
    status: str
    repo: str
    dry_run: bool
    issues_scraped: int
    clusters_found: int
    top_gaps: list[GapCluster]
    errors: list[str] = Field(default_factory=list)
