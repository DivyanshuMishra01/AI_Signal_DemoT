# Architecture — FrontierAtlas Intelligence Pipeline

## 1. System overview
The pipeline is a source-adapter architecture. Each adapter discovers and fetches source records, then normalizes them into versioned canonical records. Validation, freshness filtering, entity resolution, persistence and export are shared services.

## 2. Scale to 500,000+
Use a durable queue (Kafka, SQS or RabbitMQ) between discovery and extraction. Partition work by source and cursor; store checkpoints so workers resume after failure. Stateless workers use bounded async concurrency and per-domain token buckets. Apply backpressure when storage or providers are saturated. PostgreSQL unique constraints make writes idempotent. Horizontal scaling changes worker/queue/database capacity, not the record contract or adapter interface.

## 3. LLM reliability: 413 and 429
For 413, estimate tokens/bytes before requests, split by semantic paragraph/section boundaries, retain small overlaps, prioritize schema-relevant segments, and merge validated partial outputs. Keep raw source text in durable storage. For 429, honor Retry-After, exponential backoff with full jitter, provider-specific token buckets, circuit breakers and adaptive concurrency. Provider failure is observable and never silently replaced by invented values.

## 4. Freshness and distributed deduplication
Publication dates are parsed from structured metadata, RSS/Atom, JSON-LD and page metadata. Relative dates are interpreted against the fetch timestamp and recorded with parser provenance. A missing/ambiguous date is not considered guaranteed fresh. Only records with a normalized timestamp in `[now-24h, now]` enter the guaranteed-fresh export. Workers compute a canonical URL and content hash. PostgreSQL uniqueness on `(record_type, canonical_url)` plus transactional upserts prevents duplicate processing across nodes. A distributed lease can reduce duplicate fetches, but database constraints remain authoritative.

## 5. Storage
PostgreSQL is the primary production store for provenance, constraints, transactional deduplication and relational joins. SQLite is included for a local demo. pgvector supports semantic candidate retrieval for entity resolution; exact normalized names and alias tables remain the deterministic source of truth. A graph database such as Neo4j is optional when multi-hop traversals across founders, startups, products, papers and repositories become a dominant query pattern. Avoid operating multiple stores until access patterns justify them.

## 6. Anti-bot and compliance
Prefer official APIs, RSS/Atom and licensed datasets. Cache using ETag/Last-Modified, respect robots.txt, terms and per-host limits, and identify the crawler. Use Playwright only for permitted JavaScript-rendered pages. Do not bypass CAPTCHAs, authentication, Cloudflare challenges or Datadome controls. When blocked, stop, record the source as unavailable and seek an approved API or data agreement.

## 7. Observability
Emit structured logs and counters for fetched, parsed, rejected, fresh, duplicate, retried, rate-limited and provider-fallback records. Store rejection reasons and source provenance. Alert on freshness lag, source failure, unexpected schema drift and quota exhaustion.
