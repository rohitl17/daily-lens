# Cross-Functional Operating Model

## Team Interfaces
- Product: problem framing, metric targets, prioritization
- Design: UX systems, accessibility, interaction quality
- Engineering: architecture, reliability, implementation
- Business: pricing, monetization, growth and unit economics

## Ownership Model
- Recommendation quality: Product + Eng shared owner
- Monetization policy: Business owner, Eng implementation owner
- UX quality: Design owner, Product/Eng partners
- Reliability/SLO: Engineering owner

## Cadence
- Weekly product/design/eng triad review
- Bi-weekly growth + monetization review
- Monthly architecture and scaling checkpoint
- Quarterly roadmap reset using KPI and experiment outcomes

## Decision Artifacts
- PRD for major product changes
- Design spec for UX-impacting work
- ADR for architecture-impacting decisions
- Experiment brief for monetization/ranking changes

## Release Process
1. Spec approved (product + design + eng)
2. Feature flag enabled in staging
3. Metrics validation window
4. Progressive rollout
5. Post-launch review

## Experiment Governance
- Every experiment must define:
  - hypothesis
  - target metric
  - guardrails
  - rollback criteria
- No launch without measurable outcome framework

## Incident and Risk Handling
- Severity matrix (SEV1-SEV3)
- Incident commander rotation
- postmortem required for SEV1/SEV2
- backlog item created for every systemic root cause
