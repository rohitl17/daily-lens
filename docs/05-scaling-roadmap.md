# Scaling Roadmap to 1M DAU

## Executive Summary
Current system is prototype-grade and cannot reliably support 1M DAU as-is.

## Stage V1 (Now): Product-Market Fit Prototype
Current state:
- single backend process
- in-memory state
- synchronous ranking path
- no durable data infra

Goal:
- learn quickly and validate UX/recommendation hypotheses

## Stage V2 (10k-100k DAU): Production Foundation
Core changes:
1. Persist data
- Postgres for users, plans, entitlements, content metadata
- Redis for hot caches, rate limits, session state

2. Event pipeline
- Kafka/Kinesis for interaction events
- async feature aggregation workers

3. Feed serving improvements
- candidate generation service
- cached feed pages per user
- cursor-based pagination

4. Reliability
- metrics/tracing/logging
- alerting + runbooks
- canary/blue-green deployments

## Stage V3 (100k-1M+ DAU): Scaled Personalization Platform
Core changes:
1. Real-time ranking stack
- online feature store
- low-latency ranker service
- model lifecycle (train/validate/deploy)

2. Data and analytics
- ClickHouse/BigQuery for event analytics
- experiment platform + attribution pipeline

3. Monetization at scale
- entitlement service with strict consistency
- ad decision service with pacing/frequency capping

4. Platform hardening
- autoscaling Kubernetes workloads
- multi-AZ resilience and disaster recovery
- privacy/compliance controls

## Suggested 90-Day Plan
Days 0-30:
- DB schema + persistence migration
- cursor pagination
- baseline observability

Days 31-60:
- event stream integration
- async feature updates
- feed cache layer

Days 61-90:
- candidate/ranker service split
- experiment framework
- monetization dashboard and guardrails

## Readiness Gates for 1M DAU
- Sustained load test at target QPS
- P95/P99 latency SLO compliance
- failure-injection pass rate
- on-call and incident response maturity
