# Product Specification

## Product Purpose
DailyLens is a personalized article discovery product that balances:
- relevance (known interests)
- exploration (new domains)
- monetization (tier limits + ad-supported free experience)

## Problem Statement
Users are overwhelmed by generic news feeds and miss useful topics outside their current bubble.

## Target Users
- Primary ICP: AI Engineers and Data Scientists
- Secondary: adjacent AI stakeholders (MLOps, product engineers, research engineers)
- Long-term expansion: heterogeneous professional audiences via broader taxonomy

## Core Jobs-To-Be-Done
- "Show me high-signal content for my interests quickly"
- "Help me discover important topics I am not actively following"
- "Let me browse deeply when I choose"

## Current Product Scope
- 5 simulated users with behavior histories
- New-user onboarding flow with role, interests, and goal capture
- Personalized feed (`/api/feed`)
- Open exploration catalog (`/api/explore`)
- Interaction feedback loop (`view/like/save/share/skip` + dwell)
- Contextual bandit recommendation policy (UCB-style exploit/explore balancing)
- Referral loop with renewal discount incentives (ARRRR growth + revenue lever)
- Plan simulation (`free/silver/gold`) and ad behavior on free tier
- Dual-layer topic model:
  - User-facing umbrella for AI/Data discovery
  - System-facing subject taxonomy for extensibility
- Feed focus modes:
  - `strict` (AI-heavy relevance)
  - `balanced` (default ICP mix)
  - `discovery` (higher cross-domain exploration)

## Key User Journeys
1. Select user profile
2. Read ranked feed and interact
3. Move to Explore tab to search beyond ranked stack
4. Observe plan usage and limits
5. Refresh content pool

## Product Metrics (Current + Target)
- Activation: first feed interaction rate
- Engagement: daily active readers, sessions/user/day
- Quality: click-through rate, dwell time, save/share rates
- Exploration quality: % interactions on non-top affinity subjects
- Retention: D7 / D30
- Monetization: free->silver conversion, ARPU, ad CTR

## North-Star Metric
- Weekly retained engaged readers (users with >= N meaningful interactions/week)

## Guardrail Metrics
- Latency (feed load time)
- User frustration signals (high skip rate, early churn)
- Ad fatigue (CTR drop, increased skip/hide after ad exposure)

## Product Risks
- Over-exploration harms relevance
- Strict free limit may reduce habit formation
- Ad density can reduce trust

## Product Backlog (Near-Term)
- Explicit controls: "show less like this", "mute source/topic"
- Explainability card: "Why you’re seeing this"
- Saved collections and digest mode
- Better onboarding for cold-start users
