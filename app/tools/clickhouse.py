from typing import Any

import clickhouse_connect

from app.config import get_settings
from app.state import AgentState


def is_enabled() -> bool:
    return bool(get_settings().clickhouse_host)


def _client():
    settings = get_settings()
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
        database=settings.clickhouse_database,
        secure=settings.clickhouse_secure,
    )


def ensure_schema() -> None:
    if not is_enabled():
        return
    client = _client()
    client.command(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id String,
            repo String,
            dry_run Bool,
            issues_scraped UInt32,
            clusters_found UInt32,
            errors Array(String),
            started_at DateTime64(3, 'UTC'),
            created_at DateTime64(3, 'UTC') DEFAULT now64()
        )
        ENGINE = MergeTree
        ORDER BY (repo, created_at, run_id)
        """
    )
    client.command(
        """
        CREATE TABLE IF NOT EXISTS documentation_gaps (
            run_id String,
            repo String,
            name String,
            summary String,
            recurring_question String,
            issue_numbers Array(UInt32),
            severity String,
            confidence Float32,
            created_at DateTime64(3, 'UTC') DEFAULT now64()
        )
        ENGINE = MergeTree
        ORDER BY (repo, created_at, run_id)
        """
    )


def store_run(state: AgentState) -> None:
    if not is_enabled():
        return
    ensure_schema()
    client = _client()
    client.insert(
        "agent_runs",
        [
            [
                state.run_id,
                state.repo,
                state.dry_run,
                len(state.issues),
                len(state.clusters),
                state.errors,
                state.started_at,
            ]
        ],
        column_names=[
            "run_id",
            "repo",
            "dry_run",
            "issues_scraped",
            "clusters_found",
            "errors",
            "started_at",
        ],
    )
    rows: list[list[Any]] = []
    for cluster in state.clusters:
        rows.append(
            [
                state.run_id,
                state.repo,
                cluster.name,
                cluster.summary,
                cluster.recurring_question,
                cluster.issue_numbers,
                cluster.severity,
                cluster.confidence,
            ]
        )
    if rows:
        client.insert(
            "documentation_gaps",
            rows,
            column_names=[
                "run_id",
                "repo",
                "name",
                "summary",
                "recurring_question",
                "issue_numbers",
                "severity",
                "confidence",
            ],
        )
