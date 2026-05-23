from datetime import datetime

import httpx

from app.config import get_settings
from app.state import Issue


class GitHubToolError(RuntimeError):
    pass


async def research_repo(repo: str, limit: int) -> list[Issue]:
    settings = get_settings()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "docs-gap-agent-hackathon",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    params = {
        "state": "all",
        "per_page": min(limit, 100),
        "sort": "updated",
        "direction": "desc",
    }
    url = f"https://api.github.com/repos/{repo}/issues"

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers=headers, params=params)

    if response.status_code == 404:
        raise GitHubToolError(f"Repository not found or inaccessible: {repo}")
    if response.status_code >= 400:
        raise GitHubToolError(
            f"GitHub API failed with {response.status_code}: {response.text[:300]}"
        )

    issues: list[Issue] = []
    for item in response.json():
        if "pull_request" in item:
            continue
        issues.append(
            Issue(
                number=item["number"],
                title=item["title"],
                body=item.get("body"),
                url=item["html_url"],
                state=item["state"],
                labels=[label["name"] for label in item.get("labels", [])],
                comments_count=item.get("comments", 0),
                created_at=datetime.fromisoformat(
                    item["created_at"].replace("Z", "+00:00")
                ),
                updated_at=datetime.fromisoformat(
                    item["updated_at"].replace("Z", "+00:00")
                ),
            )
        )
    return issues
