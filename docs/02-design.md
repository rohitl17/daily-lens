# Design and UX Specification

## UX Principles
- Clarity first: users should always understand where they are and why content appears
- Low friction: fast browse + obvious next action
- Controlled complexity: advanced analytics available but not forced

## Information Architecture
- Feed tab: daily ranked stream
- Explore tab: intentional search + broader browsing
- Insights tab: model diagnostics (affinity + bandit)
- Left rail: profile + entitlement/usage
- Focus control: Strict/Balanced/Discovery toggle for relevance vs exploration

## Interaction Model
- Primary interactions: click title (view), like, save, share, skip
- Immediate feedback: card removed + recommendation state updates
- Infinite scroll on Feed tab only to avoid unexpected background churn in Explore
- Topic visibility: users see AI-first positioning while Insights surfaces core/adjacent/frontier bucketing

## Responsive Behavior
- Desktop: 2-column (`left rail + main content`)
- Mobile: content first, controls below; touch targets increased
- Tab bar always visible for quick mode switching

## Visual Language
- Calm palette with contrast for readability
- Card-based layout with clear hierarchy
- Sponsored cards visually distinct from organic content

## UX Issues Already Addressed
- Flicker reduction for status text during background loads
- RSS text cleanup to remove encoding artifacts in subtitles/summaries
- Busy layout reduced through tabbed structure

## Accessibility Requirements
- Keyboard focus visibility
- Sufficient contrast for labels/badges
- Semantic headings and landmarks
- Tap target minimum size for mobile actions

## Design Backlog
- Add compact mobile nav with sticky bottom bar
- Progressive disclosure for advanced controls
- Empty states for no-results and limit-reached contexts
- Dedicated ad transparency labels and controls
