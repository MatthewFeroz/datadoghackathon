import asyncio
import json
import os
import re
import shutil
from typing import Any

from app.config import get_settings
from app.state import GapCluster
from app.tracing import traced_tool


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64]


def _preview_result(reason: str) -> dict[str, str | None]:
    return {
        "url": None,
        "content_id": None,
        "version_id": None,
        "status": "preview",
        "reason": reason,
    }


async def publish_citeable(
    run_id: str,
    repo: str,
    cluster: GapCluster,
    dry_run: bool = True,
) -> dict[str, str | None]:
    settings = get_settings()
    with traced_tool("publish_citeable", run_id, repo):
        if dry_run:
            return _preview_result("Run is in dry-run mode; no Cited.md page was created.")
        if not settings.senso_api_key:
            return _preview_result("SENSO_API_KEY is not configured for the server.")
        if shutil.which("senso") is None:
            return _preview_result("The Senso CLI is not installed or not on PATH.")

        prompt = await _create_prompt(cluster, settings.senso_api_key)
        content_type_id = settings.senso_content_type_id or await _default_content_type_id(
            settings.senso_api_key
        )
        if content_type_id:
            generated = await _generate_sample(
                str(prompt["prompt_id"]),
                content_type_id,
                settings.senso_api_key,
            )
            markdown = _generated_markdown(generated) or cluster.draft_markdown or cluster.summary
            published = await _publish_markdown(
                cluster,
                str(prompt["prompt_id"]),
                _with_source_issues(markdown, cluster),
                settings.senso_api_key,
            )
        else:
            published = await _publish_markdown(
                cluster,
                str(prompt["prompt_id"]),
                _with_source_issues(cluster.draft_markdown or cluster.summary, cluster),
                settings.senso_api_key,
            )
        url = _published_url(published)
        if not url:
            raise RuntimeError(f"Senso publish succeeded but did not return a public URL: {published}")
        return {
            "url": url,
            "content_id": published.get("content_id"),
            "version_id": published.get("version_id"),
            "status": published.get("publish_status") or "published",
        }


async def _create_prompt(cluster: GapCluster, api_key: str) -> dict[str, Any]:
    data = {
        "question_text": _prompt_question(cluster),
        "type": "evaluation",
        "tags": ["docs-gap-agent", "human-reviewed"],
    }
    return await _run_senso_json(
        [
            "senso",
            "prompts",
            "create",
            "--data",
            json.dumps(data),
            "--output",
            "json",
            "--quiet",
        ],
        api_key,
    )


def _prompt_question(cluster: GapCluster) -> str:
    question = cluster.recurring_question.strip() or cluster.name.strip()
    if len(question) <= 500:
        return question
    return f"{question[:497].rstrip()}..."


async def _default_content_type_id(api_key: str) -> str | None:
    data = await _run_senso_json(
        [
            "senso",
            "content-types",
            "list",
            "--output",
            "json",
            "--quiet",
        ],
        api_key,
    )
    content_types = data.get("content_types")
    if not isinstance(content_types, list) or not content_types:
        return None

    for content_type in content_types:
        if isinstance(content_type, dict) and content_type.get("name") == "FAQ":
            return str(content_type["content_type_id"])
    first = content_types[0]
    if isinstance(first, dict) and first.get("content_type_id"):
        return str(first["content_type_id"])
    return None


async def _generate_sample(
    prompt_id: str,
    content_type_id: str,
    api_key: str,
) -> dict[str, Any]:
    return await _run_senso_json(
        [
            "senso",
            "generate",
            "sample",
            "--prompt-id",
            prompt_id,
            "--content-type-id",
            content_type_id,
            "--output",
            "json",
            "--quiet",
        ],
        api_key,
    )


async def _publish_markdown(
    cluster: GapCluster,
    prompt_id: str,
    markdown: str,
    api_key: str,
) -> dict[str, Any]:
    data = {
        "geo_question_id": prompt_id,
        "seo_title": cluster.draft_title or cluster.name,
        "summary": cluster.draft_summary or cluster.summary,
        "raw_markdown": markdown,
    }
    return await _run_senso_json(
        [
            "senso",
            "engine",
            "publish",
            "--data",
            json.dumps(data),
            "--output",
            "json",
            "--quiet",
        ],
        api_key,
    )


def _generated_markdown(data: dict[str, Any]) -> str | None:
    for key in ("markdown", "raw_markdown", "content", "generated_markdown"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value

    item = data.get("item")
    if isinstance(item, dict):
        for key in ("markdown", "raw_markdown", "content", "generated_markdown"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _with_source_issues(markdown: str, cluster: GapCluster) -> str:
    section = _source_issues_section(cluster)
    if "## Source GitHub issues" in markdown:
        before = markdown.split("## Source GitHub issues", 1)[0].rstrip()
        return f"{before}\n\n{section}"
    return f"{markdown.rstrip()}\n\n{section}"


def _source_issues_section(cluster: GapCluster) -> str:
    issue_lines = "\n".join(
        f"- [DataDog/dd-trace-py issue #{number}](https://github.com/DataDog/dd-trace-py/issues/{number})"
        for number in cluster.issue_numbers
    )
    if not issue_lines:
        issue_lines = "- No source GitHub issues were attached to this gap."
    return f"""## Source GitHub issues

This page was generated from the recurring issue pattern found in:

{issue_lines}
"""


async def _run_senso_json(command: list[str], api_key: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["SENSO_API_KEY"] = api_key
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await process.communicate()
    output = f"{stdout.decode()}\n{stderr.decode()}".strip()
    if process.returncode != 0:
        raise RuntimeError(output or f"Senso command failed: {' '.join(command[:3])}")
    start = output.find("{")
    if start == -1:
        raise RuntimeError(f"Senso command did not return JSON: {output[:300]}")
    return json.loads(output[start:])


def _published_url(data: dict[str, object]) -> str | None:
    publish_results = data.get("publish_results")
    if isinstance(publish_results, list):
        for result in publish_results:
            if isinstance(result, dict):
                url = _published_url(result)
                if url:
                    return url

    destinations = data.get("publish_destinations")
    if isinstance(destinations, list):
        for destination in destinations:
            if isinstance(destination, dict) and destination.get("display_url"):
                return str(destination["display_url"])
    for key in ("display_url", "public_url", "url"):
        if data.get(key):
            return str(data[key])
    content_id = data.get("content_id")
    if content_id:
        return f"https://cited.md/article/{content_id}"
    return None
