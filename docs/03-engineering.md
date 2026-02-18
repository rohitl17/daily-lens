# Engineering Specification

## v2 Laptop Architecture (Implemented)
- Backend: FastAPI monolith in `backend/main.py`
- Frontend: Next.js App Router in `frontend-app/`
- Runtime mode: `v2-laptop-production-simulation:{local|kafka}`

This version simulates production patterns on a laptop, with optional Kafka-compatible eventing.

## Data and Serving Components
- NoSQL primary store (optional):
  - MongoDB (`DATA_BACKEND=mongo`) for users, articles, interactions
  - schema-flexible documents for evolving feature payloads
- In-memory fallback:
  - users, interactions, entitlements, seen state
- In-memory "Redis stand-in":
  - feed page cache (`feed_page_cache`)
  - precomputed user rank bundles (`precomputed_rank_cache`)
  - rate limit buckets (`rate_limit_buckets`)
- In-memory "Event bus stand-in":
  - bounded queue (`event_queue`)
  - async processor thread (`_event_worker`)
- Optional Kafka-compatible pipeline:
  - producer + consumer in app process
  - broker target: Redpanda (`docker-compose.kafka.yml`)
  - backend env template: `backend/.env.kafka.example`
- In-memory "Analytics stand-in":
  - endpoint metrics (`endpoint_metrics`)
  - structured recent logs (`recent_logs`)

## API Surface
- `GET /health`
- `GET /api/users`
- `POST /api/users/focus`
- `POST /api/refresh`
- `POST /api/feed`
- `POST /api/explore`
- `POST /api/interactions`
- `GET /api/monitoring/dashboard`

## Feed Serving Path
1. Request hits `/api/feed`.
2. Per-user rate limit is checked.
3. Entitlement is evaluated.
4. Feed page cache key is resolved by `user + offset + limit + state_version`.
5. On cache miss, precomputed rank bundle is reused or rebuilt.
6. Ranked items are mixed by taxonomy buckets using per-user target mix:
   - Core AI topics
   - Adjacent topics
   - Frontier topics
7. Mix policy is determined by user role (ICP-aware) and focus mode (`strict|balanced|discovery`), then paginated and returned.

## Event Ingestion Path
1. Client sends `POST /api/interactions`.
2. Backend writes interaction synchronously and marks article as seen.
3. User cache version increments and feed/precompute caches are invalidated.
4. Event is published to Kafka if enabled, otherwise enqueued locally.
5. Consumer/worker updates per-user, per-subject stream stats.

## Recommendation Logic
- Affinity model from historical interaction action + dwell
- Bandit score from reward mean + uncertainty + novelty (UCB-style)
- Final ranking score:
  - exploit component
  - explore component
  - recency
  - stable diversity jitter
- Deterministic bucket-mix scheduling by target share deficits to keep frontier content present but not dominant

## Monetization Enforcement
- Tier limits:
  - Free: 5 posts/month
  - Silver: 50 posts/month
  - Gold: unlimited
- Server-side enforcement at interaction time (`402` over limit)
- Free-tier sponsored card injection every N organic results

## Observability
- Endpoint-level:
  - request count
  - error count
  - avg latency
  - p95 latency
  - feed cache-hit count
- Pipeline-level:
  - queue depth
  - events processed/failed/dropped
  - events published/publish-failed
- Serving-level:
  - cache entries/hits/misses
  - precomputed bundle count
- UI:
  - Monitoring tab consumes `/api/monitoring/dashboard`

## Known Gaps vs Production
- MongoDB runs as a single node in local mode (not distributed by default)
- Queue is Kafka-compatible only when Redpanda/Kafka is provisioned
- No auth, RBAC, tenancy isolation
- No background ingestion service boundary
- No index/search cluster
- No SLO alerting pipeline

## Productionization Roadmap (Next Engineering Steps)
1. Split monolith responsibilities:
   - content ingestion service
   - feed serving service
   - event processing service
2. Replace in-memory stores:
   - MongoDB sharded cluster for user/content/event documents
   - Redis for hot features, feed cache, rate limits
   - Kafka/Kinesis for event ingestion
3. Add analytics/search systems:
   - ClickHouse/BigQuery for events
   - OpenSearch/Elasticsearch for retrieval
4. Add reliability controls:
   - idempotent event keys
   - dead-letter queues
   - circuit breakers and retry policies
5. Add engineering quality gates:
   - integration tests for entitlement/ranking correctness
   - load tests for cache-hit and queue-drain behavior
