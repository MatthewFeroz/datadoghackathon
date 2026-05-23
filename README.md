# Docs Gap Agent

Hackathon MVP for an autonomous docs maintenance agent.

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set DD_API_KEY and other keys in .env, then:
chmod +x run.sh
./run.sh
```

Or run manually (loads the same Datadog LLM Observability settings from `.env`):

```bash
set -a && source .env && set +a
ddtrace-run uvicorn app.main:app --reload
```

Start a dry-run agent run:

```bash
curl -sS -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-Payment: paid' \
  -d '{"repo":"langchain-ai/langgraph","limit":25,"dry_run":true}' | jq
```

## MVP Flow

```text
POST /runs
-> payment gate
-> research GitHub issues
-> cluster recurring questions
-> optionally store in ClickHouse
-> return top gaps
```

## LangGraph Studio

The agent graph is exposed through `langgraph.json`.

```bash
source .venv/bin/activate
langgraph dev --no-browser
```

Then open:

```text
https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
```

The FastAPI endpoint still works:

```bash
uvicorn app.main:app --reload
```

```bash
curl -sS -X POST http://127.0.0.1:8000/runs \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-Payment: paid' \
  -d '{"repo":"langchain-ai/langgraph","limit":25,"dry_run":true}' | jq
```

## Environment Keys

Minimum useful setup:

```text
GITHUB_TOKEN=...
```

Optional integrations:

```text
OPENAI_API_KEY=...       # LLM clustering instead of heuristic clustering
CLICKHOUSE_HOST=...      # enables persistence
CLICKHOUSE_PASSWORD=...
SENSO_API_KEY=...        # next phase: publish cited docs
NIMBLE_API_KEY=...       # next phase: docs search / scraping fallback
GITHUB_NOTIFY_TOKEN=...  # next phase: issue comments
LANGSMITH_API_KEY=...    # LangGraph Studio traces
```

Datadog APM and LLM Observability run through `ddtrace-run`. Set `DD_API_KEY`,
`DD_SITE`, `DD_LLMOBS_ENABLED=1`, and `DD_LLMOBS_ML_APP` in `.env`, then start
with `./run.sh`. Traces appear under **APM > Traces**; LLM spans under
**LLM Observability** for the `gitshell` ML app.
