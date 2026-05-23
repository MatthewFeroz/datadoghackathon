import json
import re
from collections import defaultdict

from openai import AsyncOpenAI

from app.config import get_settings
from app.state import GapCluster, Issue


KEYWORDS = {
    "installation": ["install", "setup", "pip", "npm", "dependency", "build"],
    "authentication": ["auth", "token", "login", "permission", "credential", "401"],
    "configuration": ["config", "environment", "env", "setting", "option"],
    "deployment": ["deploy", "docker", "kubernetes", "server", "production"],
    "errors": ["error", "exception", "traceback", "failed", "crash", "bug"],
    "api usage": ["api", "example", "usage", "how to", "docs", "documentation"],
}


async def cluster_issues(issues: list[Issue]) -> list[GapCluster]:
    settings = get_settings()
    if settings.openai_api_key and len(issues) >= 2:
        try:
            clusters = await _cluster_with_llm(issues)
            if clusters:
                return clusters
        except Exception:
            pass
    return _cluster_heuristically(issues)


async def _cluster_with_llm(issues: list[Issue]) -> list[GapCluster]:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    issue_payload = [
        {
            "number": issue.number,
            "title": issue.title,
            "body": (issue.body or "")[:1200],
            "labels": issue.labels,
            "comments_count": issue.comments_count,
        }
        for issue in issues[:60]
    ]

    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You cluster GitHub issues into recurring documentation gaps. "
                    "Return JSON only with a top-level 'clusters' array. Each cluster "
                    "must have name, summary, recurring_question, issue_numbers, "
                    "severity low|medium|high, and confidence 0..1."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"issues": issue_payload}),
            },
        ],
    )
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    return [GapCluster.model_validate(item) for item in data.get("clusters", [])[:8]]


def _cluster_heuristically(issues: list[Issue]) -> list[GapCluster]:
    buckets: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        text = f"{issue.title} {issue.body or ''}".lower()
        matched = False
        for name, words in KEYWORDS.items():
            if any(word in text for word in words):
                buckets[name].append(issue)
                matched = True
        if not matched and re.search(r"\?|how|why|what|where|when", text):
            buckets["general questions"].append(issue)

    clusters: list[GapCluster] = []
    for name, bucket in sorted(buckets.items(), key=lambda item: len(item[1]), reverse=True):
        if len(bucket) < 2:
            continue
        issue_numbers = [issue.number for issue in bucket[:10]]
        example_titles = "; ".join(issue.title for issue in bucket[:3])
        severity = "high" if len(bucket) >= 5 else "medium"
        clusters.append(
            GapCluster(
                name=f"{name.title()} documentation gap",
                summary=f"{len(bucket)} recent issues appear related to {name}: {example_titles}",
                recurring_question=f"Users need clearer documentation about {name}.",
                issue_numbers=issue_numbers,
                severity=severity,
                confidence=min(0.9, 0.45 + len(bucket) / 20),
            )
        )

    if not clusters and issues:
        support_candidates = _support_gap_candidates(issues)
        if support_candidates:
            issue_numbers = [issue.number for issue in support_candidates[:10]]
            example_titles = "; ".join(issue.title for issue in support_candidates[:3])
            severity = "high" if len(support_candidates) >= 5 else "medium"
            clusters.append(
                GapCluster(
                    name="Support question documentation gap",
                    summary=(
                        f"{len(support_candidates)} recent issues look like recurring "
                        f"support or usage questions: {example_titles}"
                    ),
                    recurring_question=(
                        "Users need clearer troubleshooting and usage documentation for "
                        "the recurring questions appearing in recent issues."
                    ),
                    issue_numbers=issue_numbers,
                    severity=severity,
                    confidence=min(0.8, 0.4 + len(support_candidates) / 25),
                )
            )

    return clusters[:8]


def _support_gap_candidates(issues: list[Issue]) -> list[Issue]:
    candidates: list[Issue] = []
    for issue in issues:
        text = f"{issue.title} {issue.body or ''}".lower()
        labels = {label.lower() for label in issue.labels}
        if (
            "question" in labels
            or "documentation" in labels
            or "docs" in labels
            or issue.comments_count >= 2
            or re.search(r"\b(how|why|what|where|when|can i|is there)\b|\?", text)
        ):
            candidates.append(issue)
    return candidates


def attach_review_drafts(clusters: list[GapCluster], issues: list[Issue]) -> list[GapCluster]:
    issue_by_number = {issue.number: issue for issue in issues}
    for cluster in clusters:
        related = [
            issue_by_number[number]
            for number in cluster.issue_numbers
            if number in issue_by_number
        ]
        title = f"{cluster.name}: {cluster.recurring_question}".strip()
        title = title[:110]
        issue_lines = "\n".join(
            f"- #{issue.number}: [{issue.title}]({issue.url})" for issue in related[:8]
        )
        if not issue_lines:
            issue_lines = "- No linked issues were available for this draft."
        example_title = related[0].title if related else cluster.recurring_question

        cluster.draft_title = title
        cluster.draft_summary = (
            f"Draft documentation response for {len(related)} GitHub issues in "
            f"{cluster.name.lower()}."
        )
        cluster.draft_markdown = f"""# {title}

Resolve this `dd-trace-py` documentation gap with a task-oriented Datadog-style guide.

> This page was generated from recurring GitHub issues and should be reviewed before it is linked from public support threads.

## Overview

{cluster.summary}

This page answers the recurring question: **{cluster.recurring_question}**

## Getting started

Before you begin, make sure you have:

- A Python service instrumented with `dd-trace-py`.
- A Datadog account with APM enabled.
- A running Datadog Agent, or an agentless trace intake path configured for your environment.
- Access to the service configuration where tracing environment variables or integration settings are defined.

Install or update the Python tracing library:

```shell
pip install --upgrade ddtrace
```

If your service already uses `ddtrace`, confirm the installed version:

```shell
python -m pip show ddtrace
```

## Instrument your application

Run the service with `ddtrace-run` so supported libraries are instrumented automatically:

```shell
ddtrace-run python app.py
```

For production services, set unified service tags before starting the process:

```shell
export DD_SERVICE=<SERVICE_NAME>
export DD_ENV=<ENVIRONMENT>
export DD_VERSION=<VERSION>

ddtrace-run python app.py
```

## Configuration

The Python SDK is commonly configured with environment variables. Start with these values and add integration-specific settings as needed:

| Setting | Description |
| --- | --- |
| `DD_SERVICE` | Service name shown in Datadog APM. |
| `DD_ENV` | Deployment environment, such as `dev`, `staging`, or `prod`. |
| `DD_VERSION` | Application version for release correlation. |
| `DD_AGENT_HOST` | Hostname for the Datadog Agent when it is not on `localhost`. |
| `DD_TRACE_AGENT_URL` | Full trace intake URL. Takes precedence over host and port settings. |

For the issue pattern behind this gap, document the exact setting, supported `ddtrace` version, and any framework-specific caveats.

## Example

1. Review the affected service and identify where `ddtrace` is configured.
2. Confirm the Datadog Agent or agentless intake path is already working.
3. Apply the configuration change described in this guide.
4. Restart the service so the tracing configuration is loaded.

```shell
DD_SERVICE=<SERVICE_NAME> \\
DD_ENV=prod \\
DD_VERSION=1.0.0 \\
DD_AGENT_HOST=<DATADOG_AGENT_HOST> \\
ddtrace-run python app.py
```

## Validation

Run the SDK diagnostic command:

```shell
ddtrace-run --info
```

Then validate the result in Datadog:

- Generate traffic for the affected endpoint or background job.
- Open **APM > Traces** in Datadog.
- Confirm the trace, span metadata, and any expected request or response fields are present.
- Compare the result against the issue example: "{example_title}".

## Troubleshooting

- If traces do not appear, confirm the Datadog Agent is reachable from the service.
- If the Agent runs in a container, confirm APM non-local traffic is enabled and `DD_AGENT_HOST` points to the Agent container or host.
- If configuration changes are ignored, verify that the service was restarted after updating environment variables.
- If only some spans are missing metadata, check whether the integration supports that setting for the installed `dd-trace-py` version.
- If `ddtrace-run --info` does not show the expected values, check whether configuration is being overridden in code or by deployment-level environment variables.

## Source GitHub issues
{issue_lines}

## Further reading

- [Datadog Python tracing documentation](https://ddtrace.readthedocs.io/)
- [Datadog APM documentation](https://docs.datadoghq.com/tracing/)
- [dd-trace-py GitHub repository](https://github.com/DataDog/dd-trace-py)

## Review metadata

- Severity: {cluster.severity}
- Confidence: {cluster.confidence:.0%}
- Generated by Git Shell for human review before publishing.
"""
    return clusters
