from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.state import DocSource, GapCluster


async def search_official_docs(
    repo: str,
    docs_url: str | None,
    clusters: list[GapCluster],
) -> list[DocSource]:
    sources: list[DocSource] = []
    if docs_url:
        sources.extend(await _extract_docs_url(docs_url, clusters))

    owner, name = repo.split("/", 1)
    sources.append(
        DocSource(
            title=f"{repo} GitHub README",
            url=f"https://github.com/{owner}/{name}",
            snippet=(
                "Repository README and project metadata are treated as first-party "
                "documentation evidence for the agent's gap analysis."
            ),
            source_type="repo_readme",
            confidence=0.75,
        )
    )
    return sources[:8]


async def _extract_docs_url(
    docs_url: str, clusters: list[GapCluster]
) -> list[DocSource]:
    settings = get_settings()
    if not settings.nimble_api_key:
        return await _fetch_docs_url(docs_url, clusters)

    try:
        return await _extract_docs_url_with_nimble(docs_url, clusters)
    except Exception as exc:
        fallback_sources = await _fetch_docs_url(docs_url, clusters)
        fallback_sources.insert(
            0,
            DocSource(
                title="Nimble extraction unavailable",
                url=docs_url,
                snippet=(
                    "Nimble was configured but could not extract this docs URL. "
                    f"Falling back to direct fetch. Error: {exc}"
                ),
                source_type="nimble_extract_error",
                confidence=0.3,
            ),
        )
        return fallback_sources


async def _extract_docs_url_with_nimble(
    docs_url: str, clusters: list[GapCluster]
) -> list[DocSource]:
    try:
        from langchain_nimble import NimbleExtractRetriever
    except ImportError as exc:
        raise RuntimeError(
            "langchain-nimble is not installed. Install it in the active virtualenv."
        ) from exc

    from pydantic import SecretStr

    settings = get_settings()
    retriever = NimbleExtractRetriever(
        api_key=SecretStr(settings.nimble_api_key or ""),
        output_format="markdown",
    )
    docs = await retriever.ainvoke(docs_url)

    sources: list[DocSource] = []
    gap_terms = ", ".join(cluster.name for cluster in clusters[:3])
    for doc in docs[:3]:
        metadata = getattr(doc, "metadata", {}) or {}
        source_url = str(metadata.get("url") or metadata.get("source") or docs_url)
        title = str(metadata.get("title") or "").strip()
        if not title:
            parsed = urlparse(source_url)
            title = parsed.netloc.replace(".", " ") or docs_url
        text = " ".join(getattr(doc, "page_content", "").split())
        snippet = text[:900]
        if gap_terms:
            snippet = f"Nimble extracted docs evidence for gaps: {gap_terms}. {snippet}"
        sources.append(
            DocSource(
                title=title[:120],
                url=source_url,
                snippet=snippet or "Nimble extracted this documentation URL.",
                source_type="nimble_extract",
                confidence=0.9,
            )
        )

    if not sources:
        raise RuntimeError("Nimble returned no extracted documents.")
    return sources


async def _fetch_docs_url(
    docs_url: str, clusters: list[GapCluster]
) -> list[DocSource]:
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            response = await client.get(
                docs_url,
                headers={"User-Agent": "docs-gap-agent-hackathon"},
            )
        response.raise_for_status()
    except Exception as exc:
        return [
            DocSource(
                title="Official docs source unavailable",
                url=docs_url,
                snippet=f"The configured docs URL could not be fetched: {exc}",
                source_type="official_docs_error",
                confidence=0.25,
            )
        ]

    text = " ".join(response.text.split())
    parsed = urlparse(str(response.url))
    title = parsed.netloc or docs_url
    if "<title>" in response.text.lower():
        lower = response.text.lower()
        start = lower.find("<title>")
        end = lower.find("</title>", start)
        if start != -1 and end != -1:
            title = response.text[start + 7 : end].strip()[:120] or title

    gap_terms = ", ".join(cluster.name for cluster in clusters[:3])
    snippet = text[:600]
    if gap_terms:
        snippet = f"Configured first-party docs source for gaps: {gap_terms}. {snippet}"

    return [
        DocSource(
            title=title,
            url=str(response.url),
            snippet=snippet,
            source_type="official_docs",
            confidence=0.85,
        )
    ]
