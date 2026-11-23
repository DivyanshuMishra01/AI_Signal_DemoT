# FrontierAtlas — AI Intelligence Ingestion Pipeline

An evidence-first, asynchronous pipeline for collecting and normalizing AI ecosystem intelligence. It covers startups, AI products, research papers, GitHub metrics, fresh news and fresh jobs.

## What this implementation does

- Async HTTP ingestion with bounded concurrency, per-host pacing, `Retry-After`, exponential backoff and jitter.
- Source-specific adapters: YC OSS directory (configurable JSON endpoint), Hugging Face Hub models/spaces, arXiv Atom API, GitHub REST, RSS and job-board JSON/RSS.
- LLM fallback chain (Gemini, Groq, DeepSeek) for unstructured extraction only; API-native fields remain deterministic.
- Payload-aware chunking, strict JSON parsing and Pydantic validation.
- UTC date normalization and a strict 24-hour gate for jobs/news.
- Deterministic + fuzzy entity resolution with a review log.
- Idempotent SQLite persistence using unique source URLs and content hashes.
- Six-tab Excel export; CSV exports are also generated for portability.

## Important data-integrity note

This repository contains **no fabricated records**. Running it acquires live records from configured public sources. The 1,000/1,000/1,000 targets are acceptance thresholds, not claims about data already collected. A run may produce fewer records if a source changes, rate-limits the client, or does not expose enough verified entities. The run report records counts and source failures. Do not submit a target as achieved unless the generated output actually meets it.

Some directories do not provide a stable public API or authoritative company metadata. The YC source URL is configurable and should be verified against the currently published YC OSS data endpoint before a production run. Hugging Face models/spaces are classified as AI products/tools only when their metadata supports that interpretation; they are not automatically treated as incorporated startups.

## Quick start

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add GITHUB_TOKEN for reliable GitHub enrichment.
frontieratlas --mode all --targets startups=1000,products=1000,research=1000
pytest -q
```

If the CLI command is not available immediately, use:
```bash
python -m frontieratlas.cli --mode all
```

## Modes

```bash
frontieratlas --mode startups
frontieratlas --mode products
frontieratlas --mode research
frontieratlas --mode signals
frontieratlas --mode all
frontieratlas --export
```

Configuration is in `configs/sources.yaml`. Output is written to `data/exports/intelligence.xlsx`, per-tab CSV files, `data/run_report.json`, and `logs/pipeline.jsonl`.

## Sources

| Vertical | Source | Method | Evidence kept |
|---|---|---|---|
| Startups | YC OSS directory | Configurable JSON feed | Source URL, original name, description, batch |
| Products | Hugging Face Hub models and Spaces | Paginated REST API | Model/Space URL, owner, downloads/likes |
| Research | arXiv | Atom API pagination | arXiv URL, authors, published date, abstract |
| Research metrics | GitHub REST | Repository lookup | Repository URL, current stars, fetched timestamp |
| News | TechCrunch AI, VentureBeat, MIT Tech Review, The Verge AI, Google News AI | RSS + article fetch | Original URL, feed date, article text |
| Jobs | RemoteOK, Arbeitnow, Remotive, Jobicy, We Work Remotely | JSON/RSS | Original URL, board date, full description |

Check each source's terms, robots policy, rate limits and API documentation before deployment. Prefer official APIs and feeds. For protected sites, use licensed APIs or permission-based browser automation; do not evade CAPTCHAs, access controls or bot challenges.

## Architecture

`Discovery -> Fetch -> Parse -> Normalize -> Validate -> (LLM if needed) -> Resolve -> Persist -> Export`

- **Scale:** stateless workers partitioned by source and cursor; queue-based fan-out; per-host concurrency; checkpointed pagination; backpressure. Increase worker count and database capacity without changing parsing contracts.
- **413:** semantic chunking with token/byte budgets, overlap, structured field prioritization and bounded retries; never blindly truncate the only copy of source text.
- **429:** honor `Retry-After`, exponential backoff with full jitter, provider-specific token buckets, circuit breakers and concurrency reduction.
- **Freshness/dedup:** normalize publication times to UTC; reject missing/unparseable dates from the guaranteed-fresh set; use `(record_type, canonical_url)` uniqueness plus content hashes; database transactions make concurrent inserts idempotent.
- **Storage:** PostgreSQL is recommended for production relational truth, constraints and concurrent writes; SQLite is the zero-configuration demo backend. Add pgvector for semantic candidate retrieval and Neo4j only when multi-hop graph traversals justify a separate graph store. Keep canonical entities and provenance in PostgreSQL.
- **Anti-bot:** official feeds/APIs first; cache with ETags/Last-Modified; identify the crawler; respect robots.txt, terms and rate limits. For JS-heavy sources use Playwright only where permitted. If challenged, stop and use a licensed feed/API or request access—never claim CAPTCHA bypass.

## Schema and provenance

Every exported row carries a `source_url`, `source_name`, `collected_at`, and stable `record_id`. News/job rows additionally carry `published_at` and `freshness_verified`. Research rows carry `paper_url`, `github_url`, `github_stars`, and `github_metrics_fetched_at`. Missing values remain null; LLMs are not allowed to invent URLs, dates, employee counts, pricing or stars.

## LLM provider setup

Set one or more API keys in `.env`. Provider calls are optional for API-native records. The orchestrator falls through on quota, timeout, malformed output or oversized payload. If all providers fail, records are marked for review rather than hallucinated.

## Deliverables and honest status

This is a runnable engineering foundation, not proof that the 3,000-row target has already been achieved. Run the pipeline, inspect `run_report.json`, validate every URL and timestamp, then publish the generated workbook and repository. The submission form is the one supplied in the assignment brief.
