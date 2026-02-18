"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArticleCard } from "@/components/article-card";
import { exploreCatalog, getFeed, getHealth, getMonitoringDashboard, getUsers, onboardUser, refreshContent, sendInteraction, simulateReferralSignup, updateUserFocusMode } from "@/lib/api";
import type { Entitlement, FeedItem, InteractionAction, MonitoringDashboard, User } from "@/lib/types";

type ItemWithMountTime = FeedItem & { mountedAt: number };
type ViewTab = "feed" | "explore" | "onboarding";
type ProfileTab = "account" | "preferences" | "system";

const FEED_PAGE_SIZE = 18;
const CATALOG_PAGE_SIZE = 12;
const AI_INTERESTS = ["LLMs", "RAG", "Agents", "MLOps", "Evaluation", "AI Safety", "Inference", "Data Pipelines"];
const FOCUS_OPTIONS = ["strict", "balanced", "discovery"] as const;

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function FeedApp() {
  const [status, setStatus] = useState("Booting discovery engine...");
  const [users, setUsers] = useState<User[]>([]);
  const [currentUser, setCurrentUser] = useState<string>("");
  const [activeTab, setActiveTab] = useState<ViewTab>("feed");

  const [items, setItems] = useState<ItemWithMountTime[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const [catalogItems, setCatalogItems] = useState<ItemWithMountTime[]>([]);
  const [catalogOffset, setCatalogOffset] = useState(0);
  const [catalogHasMore, setCatalogHasMore] = useState(false);
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [catalogLoading, setCatalogLoading] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchSubject, setSearchSubject] = useState("");
  const [includeSeen, setIncludeSeen] = useState(false);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [entitlement, setEntitlement] = useState<Entitlement | null>(null);

  const [affinity, setAffinity] = useState<Record<string, number>>({});
  const [explorationScores, setExplorationScores] = useState<Record<string, number>>({});
  const [pulls, setPulls] = useState<Record<string, number>>({});
  const [monitoring, setMonitoring] = useState<MonitoringDashboard | null>(null);
  const [monitoringLoading, setMonitoringLoading] = useState(false);
  const [rateLimitedUntilMs, setRateLimitedUntilMs] = useState(0);
  const [onboardingName, setOnboardingName] = useState("");
  const [onboardingRole, setOnboardingRole] = useState("AI Engineer");
  const [onboardingGoal, setOnboardingGoal] = useState("Stay current in AI in 10 minutes/day");
  const [onboardingReferralCode, setOnboardingReferralCode] = useState("");
  const [onboardingInterests, setOnboardingInterests] = useState<string[]>(["LLMs", "RAG"]);
  const [onboardingLoading, setOnboardingLoading] = useState(false);
  const [referralLoading, setReferralLoading] = useState(false);
  const [focusLoading, setFocusLoading] = useState(false);
  const [onboardingFocusMode, setOnboardingFocusMode] = useState<"strict" | "balanced" | "discovery">("balanced");
  const [topicBuckets, setTopicBuckets] = useState<Record<string, "core" | "adjacent" | "frontier">>({});
  const [targetMix, setTargetMix] = useState<Record<string, number>>({});
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileTab, setProfileTab] = useState<ProfileTab>("account");

  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const parseRetryAfterSeconds = (rawError: string): number => {
    const m = rawError.match(/"retry_after_seconds"\s*:\s*(\d+)/);
    if (!m) return 5;
    const v = Number(m[1]);
    return Number.isFinite(v) && v > 0 ? v : 5;
  };

  const hydrateFeed = useCallback(
    async (reset: boolean, options?: { silent?: boolean }) => {
      const silent = options?.silent ?? false;
      if (Date.now() < rateLimitedUntilMs) return;
      if (!currentUser || loading || (!hasMore && !reset)) return;
      setLoading(true);
      if (!silent && reset) {
        setStatus("Curating your feed...");
      }

      try {
        const nextOffset = reset ? 0 : offset;
        const feed = await getFeed(currentUser, nextOffset, FEED_PAGE_SIZE);

        const withTimes = feed.items.map((i) => ({ ...i, mountedAt: performance.now() }));

        setItems((prev) => (reset ? withTimes : [...prev, ...withTimes]));
        setOffset(feed.next_offset);
        setHasMore(feed.has_more);
        setAffinity(feed.subject_affinity);
        setExplorationScores(feed.exploration_subject_scores ?? feed.bandit_subject_scores ?? {});
        setPulls(feed.subject_pull_counts);
        setEntitlement(feed.entitlement);
        setTopicBuckets(feed.topic_buckets ?? {});
        setTargetMix(feed.target_mix ?? {});
        setSubjects(Object.keys(feed.subject_affinity));

        if (!silent) {
          setStatus(
            feed.message ?? (feed.has_more ? "Feed ready. Scroll for more stories." : "You reached the end of this session")
          );
        }
      } catch (error) {
        const message = (error as Error).message || "";
        if (message.includes("429")) {
          const retryAfterSeconds = parseRetryAfterSeconds(message);
          setRateLimitedUntilMs(Date.now() + retryAfterSeconds * 1000);
          setStatus(`Rate limited. Retrying feed in about ${retryAfterSeconds}s.`);
        } else {
          setStatus(`Feed load failed: ${message}`);
        }
      } finally {
        setLoading(false);
      }
    },
    [currentUser, hasMore, loading, offset, rateLimitedUntilMs]
  );

  const runCatalogSearch = useCallback(
    async (reset: boolean) => {
      if (Date.now() < rateLimitedUntilMs) return;
      if (!currentUser || catalogLoading) return;
      setCatalogLoading(true);

      try {
        const response = await exploreCatalog({
          userId: currentUser,
          query: searchQuery,
          subject: searchSubject,
          includeSeen,
          offset: reset ? 0 : catalogOffset,
          limit: CATALOG_PAGE_SIZE,
        });

        const withTimes = response.items.map((i) => ({ ...i, mountedAt: performance.now() }));
        setCatalogItems((prev) => (reset ? withTimes : [...prev, ...withTimes]));
        setCatalogOffset(response.next_offset);
        setCatalogHasMore(response.has_more);
        setCatalogTotal(response.total);
        setEntitlement(response.entitlement);
        if (!subjects.length) {
          setSubjects(response.subjects);
        }

        setStatus(
          response.message ??
            (response.total ? `Catalog results: ${response.total}` : "No results found. Try another keyword.")
        );
      } catch (error) {
        const message = (error as Error).message || "";
        if (message.includes("429")) {
          const retryAfterSeconds = parseRetryAfterSeconds(message);
          setRateLimitedUntilMs(Date.now() + retryAfterSeconds * 1000);
          setStatus(`Rate limited. Retry catalog search in about ${retryAfterSeconds}s.`);
        } else {
          setStatus(`Catalog search failed: ${message}`);
        }
      } finally {
        setCatalogLoading(false);
      }
    },
    [catalogLoading, catalogOffset, currentUser, includeSeen, rateLimitedUntilMs, searchQuery, searchSubject, subjects.length]
  );

  const track = useCallback(
    async (articleId: string, action: InteractionAction, dwellSeconds: number) => {
      if (!currentUser) return;
      try {
        const interactionResult = await sendInteraction({
          userId: currentUser,
          articleId,
          action,
          dwellSeconds,
        });
        if ((interactionResult as { entitlement?: Entitlement }).entitlement) {
          setEntitlement((interactionResult as { entitlement: Entitlement }).entitlement);
        }

        let remainingAfterRemoval = 0;
        setItems((prev) => {
          const next = prev.filter((x) => x.id !== articleId);
          remainingAfterRemoval = next.length;
          return next;
        });
        setCatalogItems((prev) => prev.filter((x) => x.id !== articleId));
        setStatus(`Tracked ${action}. Recommendations updated.`);

        const head = await getFeed(currentUser, 0, 1);
        setAffinity(head.subject_affinity);
        setExplorationScores(head.exploration_subject_scores ?? head.bandit_subject_scores ?? {});
        setPulls(head.subject_pull_counts);
        setTopicBuckets(head.topic_buckets ?? {});
        setTargetMix(head.target_mix ?? {});
        setEntitlement(head.entitlement);

        if (remainingAfterRemoval < 8) {
          await hydrateFeed(false, { silent: true });
        }
      } catch (error) {
        const text = (error as Error).message || "";
        if (text.includes("402")) {
          setStatus("Monthly post limit reached. Upgrade tier to continue reading more posts.");
        } else {
          setStatus(`Interaction failed: ${text}`);
        }
      }
    },
    [currentUser, hydrateFeed]
  );

  const handleUserChange = (userId: string) => {
    setCurrentUser(userId);
    setActiveTab("feed");
    setRateLimitedUntilMs(0);
    setOffset(0);
    setItems([]);
    setHasMore(true);

    setCatalogItems([]);
    setCatalogOffset(0);
    setCatalogHasMore(false);
    setCatalogTotal(0);
    setEntitlement(null);

    setStatus(`Loading ${userId} profile...`);
  };

  const currentUserObj = useMemo(() => users.find((u) => u.id === currentUser) ?? null, [currentUser, users]);
  const currentFocusMode = (currentUserObj?.focus_mode ?? "balanced") as "strict" | "balanced" | "discovery";
  const onboardingReadiness = useMemo(() => {
    let score = 0;
    if (onboardingName.trim().length >= 2) score += 40;
    if (onboardingRole.trim().length >= 2) score += 20;
    if (onboardingGoal.trim().length >= 4) score += 20;
    if (onboardingInterests.length > 0) score += 20;
    return score;
  }, [onboardingGoal, onboardingInterests.length, onboardingName, onboardingRole]);

  const topAffinitySubjects = useMemo(
    () =>
      Object.entries(affinity)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([subject]) => subject),
    [affinity]
  );

  const topPicks = useMemo(() => {
    const s = new Set(topAffinitySubjects);
    return items.filter((x) => s.has(x.subject));
  }, [items, topAffinitySubjects]);

  const discovery = useMemo(() => {
    const s = new Set(topAffinitySubjects);
    return items.filter((x) => !s.has(x.subject));
  }, [items, topAffinitySubjects]);

  const reloadUsers = useCallback(async () => {
    const loadedUsers = await getUsers();
    setUsers(loadedUsers);
    return loadedUsers;
  }, []);

  const toggleInterest = (interest: string) => {
    setOnboardingInterests((prev) =>
      prev.includes(interest) ? prev.filter((x) => x !== interest) : [...prev, interest]
    );
  };

  const submitOnboarding = useCallback(async () => {
    if (!onboardingName.trim()) {
      setStatus("Please provide a name for onboarding.");
      return;
    }
    setOnboardingLoading(true);
    try {
      const selectedInterests = onboardingInterests.length ? onboardingInterests : ["LLMs"];
      const response = await onboardUser({
        name: onboardingName.trim(),
        role: onboardingRole.trim(),
        interests: selectedInterests,
        goal: onboardingGoal.trim(),
        referralCode: onboardingReferralCode.trim() || undefined,
        focusMode: onboardingFocusMode,
      });
      const loadedUsers = await reloadUsers();
      setRateLimitedUntilMs(0);
      setCurrentUser(response.user.id);
      setActiveTab("feed");
      setEntitlement(response.entitlement);
      setItems([]);
      setOffset(0);
      setHasMore(true);
      setStatus(response.message);
      // Hydrate first page immediately so onboarding ends on usable feed state.
      const head = await getFeed(response.user.id, 0, FEED_PAGE_SIZE);
      const withTimes = head.items.map((i) => ({ ...i, mountedAt: performance.now() }));
      setItems(withTimes);
      setOffset(head.next_offset);
      setHasMore(head.has_more);
      setAffinity(head.subject_affinity);
      setExplorationScores(head.exploration_subject_scores ?? head.bandit_subject_scores ?? {});
      setPulls(head.subject_pull_counts);
      setEntitlement(head.entitlement);
      setTopicBuckets(head.topic_buckets ?? {});
      setTargetMix(head.target_mix ?? {});
      setSubjects(Object.keys(head.subject_affinity));
      setOnboardingName("");
      setOnboardingReferralCode("");
      setOnboardingInterests(["LLMs", "RAG"]);
      setOnboardingFocusMode("balanced");
      setUsers(loadedUsers);
    } catch (error) {
      setStatus(`Onboarding failed: ${(error as Error).message}`);
    } finally {
      setOnboardingLoading(false);
    }
  }, [onboardingFocusMode, onboardingGoal, onboardingInterests, onboardingName, onboardingReferralCode, onboardingRole, reloadUsers]);

  const handleFocusModeChange = useCallback(
    async (mode: "strict" | "balanced" | "discovery") => {
      if (!currentUser || mode === currentFocusMode) return;
      setFocusLoading(true);
      try {
        await updateUserFocusMode({ userId: currentUser, focusMode: mode });
        const loadedUsers = await reloadUsers();
        setUsers(loadedUsers);
        setStatus(`Feed focus set to ${mode}. Recomputing recommendations...`);
        // Avoid blank UI while switching scenario: fetch replacement page then swap in state.
        setRateLimitedUntilMs(0);
        const nextFeed = await getFeed(currentUser, 0, FEED_PAGE_SIZE);
        const withTimes = nextFeed.items.map((i) => ({ ...i, mountedAt: performance.now() }));
        setItems(withTimes);
        setOffset(nextFeed.next_offset);
        setHasMore(nextFeed.has_more);
        setAffinity(nextFeed.subject_affinity);
        setExplorationScores(nextFeed.exploration_subject_scores ?? nextFeed.bandit_subject_scores ?? {});
        setPulls(nextFeed.subject_pull_counts);
        setTopicBuckets(nextFeed.topic_buckets ?? {});
        setTargetMix(nextFeed.target_mix ?? {});
        setEntitlement(nextFeed.entitlement);
        setSubjects(Object.keys(nextFeed.subject_affinity));
        setStatus("Recommendation scenario updated.");
      } catch (error) {
        setStatus(`Focus mode update failed: ${(error as Error).message}`);
      } finally {
        setFocusLoading(false);
      }
    },
    [currentFocusMode, currentUser, hydrateFeed, reloadUsers]
  );

  const simulateReferral = useCallback(async () => {
    if (!currentUser) return;
    setReferralLoading(true);
    try {
      const ts = Date.now().toString().slice(-4);
      const result = await simulateReferralSignup({
        inviterUserId: currentUser,
        inviteeName: `AI User ${ts}`,
        inviteeRole: "Data Scientist",
        interests: ["LLMs", "MLOps"],
      });
      const loadedUsers = await reloadUsers();
      setUsers(loadedUsers);
      setStatus(
        `Referral success: ${result.new_user.name} joined. Renewal discount now ${result.inviter_renewal_discount_percent}%`
      );
    } catch (error) {
      setStatus(`Referral failed: ${(error as Error).message}`);
    } finally {
      setReferralLoading(false);
    }
  }, [currentUser, reloadUsers]);

  useEffect(() => {
    // Initial bootstrapping of health and default profile.
    const boot = async () => {
      try {
        await getHealth();
        const loadedUsers = await reloadUsers();
        setUsers(loadedUsers);
        setCurrentUser(loadedUsers[0]?.id ?? "");
        setHasMore(true);
        setStatus("Platform online. Pick a profile and start exploring.");
      } catch (error) {
        setStatus(`Backend unavailable: ${(error as Error).message}`);
      }
    };

    void boot();
  }, [reloadUsers]);

  useEffect(() => {
    // When active user changes, reset feed from offset 0.
    if (!currentUser) return;
    void hydrateFeed(true);
  }, [currentUser, hydrateFeed]);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node) return;

    // Preload early to keep infinite-scroll experience smooth.
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && activeTab === "feed") {
            void hydrateFeed(false, { silent: true });
          }
        });
      },
      { rootMargin: "1200px 0px" }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [activeTab, hydrateFeed]);

  const fetchMonitoring = useCallback(async () => {
    setMonitoringLoading(true);
    try {
      const dashboard = await getMonitoringDashboard();
      setMonitoring(dashboard);
      setStatus("Monitoring snapshot updated.");
    } catch (error) {
      setStatus(`Monitoring fetch failed: ${(error as Error).message}`);
    } finally {
      setMonitoringLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!profileOpen || profileTab !== "system") return;
    void fetchMonitoring();
  }, [fetchMonitoring, profileOpen, profileTab]);

  return (
    <div className="app-shell single-layout">
      <main className="content">
        <header className="topbar clean-topbar">
          <div>
            <p className="eyebrow">DailyLens</p>
            <h2>Your Daily Discovery Feed</h2>
          </div>
          <div className="topbar-controls">
            <button className={`small-btn ${activeTab === "onboarding" ? "" : "ghost"}`} onClick={() => setActiveTab("onboarding")}>
              New User
            </button>
            <button className="small-btn" onClick={() => setProfileOpen(true)}>
              Profile
            </button>
          </div>
        </header>
        <div className="status-chip wide-status">{loading ? "Updating feed..." : status}</div>
        <section className="kpi-strip">
          <article className="kpi-card">
            <p>Reader</p>
            <strong>{currentUserObj?.name ?? "Not selected"}</strong>
            <span>{currentUserObj?.role ?? "Pick a profile to begin"}</span>
          </article>
          <article className="kpi-card">
            <p>Plan</p>
            <strong>{(entitlement?.tier ?? currentUserObj?.tier ?? "free").toUpperCase()}</strong>
            <span>
              {entitlement?.monthly_remaining === null
                ? "Unlimited reads"
                : `${entitlement?.monthly_remaining ?? 0} posts left this month`}
            </span>
          </article>
          <article className="kpi-card">
            <p>Focus</p>
            <strong>{currentFocusMode.charAt(0).toUpperCase() + currentFocusMode.slice(1)}</strong>
            <span>
              Core {Math.round((targetMix.core ?? 0) * 100)}% • Adjacent {Math.round((targetMix.adjacent ?? 0) * 100)}% • Frontier {Math.round((targetMix.frontier ?? 0) * 100)}%
            </span>
          </article>
        </section>

        <section className="tab-row" aria-label="Views">
          <button className={`tab-btn ${activeTab === "feed" ? "active" : ""}`} onClick={() => setActiveTab("feed")}>Feed</button>
          <button className={`tab-btn ${activeTab === "explore" ? "active" : ""}`} onClick={() => setActiveTab("explore")}>Explore</button>
        </section>

        {activeTab === "feed" ? (
          <>
            <section className="feed-section">
              <div className="section-head">
                <h3>Top Picks</h3>
                <span>High-confidence recommendations</span>
              </div>
              <div className="article-grid">
                {topPicks.slice(0, 8).map((item) => (
                  <ArticleCard
                    key={item.id}
                    item={item}
                    mountedAt={item.mountedAt}
                    onAction={track}
                    onLinkClick={async (articleId, dwellSeconds) => track(articleId, "view", dwellSeconds)}
                  />
                ))}
              </div>
            </section>

            <section className="feed-section">
              <div className="section-head">
                <h3>Explore New Domains</h3>
                <span>Deliberate novelty from under-sampled subjects</span>
              </div>
              <div className="article-grid">
                {discovery.map((item) => (
                  <ArticleCard
                    key={item.id}
                    item={item}
                    mountedAt={item.mountedAt}
                    onAction={track}
                    onLinkClick={async (articleId, dwellSeconds) => track(articleId, "view", dwellSeconds)}
                  />
                ))}
              </div>
            </section>
          </>
        ) : null}

        {activeTab === "explore" ? (
          <>
            <section className="feed-section">
              <div className="section-head">
                <h3>Search Catalog</h3>
                <span>Look beyond the ranked feed</span>
              </div>
              <div className="search-row">
                <input
                  placeholder="Search topics, sources, or keywords"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      void runCatalogSearch(true);
                    }
                  }}
                />
                <button className="small-btn" onClick={() => void runCatalogSearch(true)}>
                  Search
                </button>
              </div>
              <div className="search-filters">
                <select value={searchSubject} onChange={(e) => setSearchSubject(e.target.value)}>
                  <option value="">All subjects</option>
                  {subjects.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                <label>
                  <input type="checkbox" checked={includeSeen} onChange={(e) => setIncludeSeen(e.target.checked)} />
                  Include read
                </label>
                <button
                  className="small-btn ghost"
                  onClick={() => {
                    setSearchQuery("");
                    setSearchSubject("");
                    setCatalogItems([]);
                    setCatalogOffset(0);
                    setCatalogHasMore(false);
                    setCatalogTotal(0);
                  }}
                >
                  Clear
                </button>
              </div>
            </section>

            <section className="feed-section">
              <div className="section-head">
                <h3>Open Catalog</h3>
                <span>{catalogTotal ? `${catalogTotal} results` : "Search to load results"}</span>
              </div>
              <div className="article-grid">
                {catalogItems.map((item) => (
                  <ArticleCard
                    key={`catalog-${item.id}-${item.mountedAt}`}
                    item={item}
                    mountedAt={item.mountedAt}
                    onAction={track}
                    onLinkClick={async (articleId, dwellSeconds) => track(articleId, "view", dwellSeconds)}
                  />
                ))}
              </div>
              {catalogHasMore ? (
                <button className="small-btn" onClick={() => void runCatalogSearch(false)} disabled={catalogLoading}>
                  {catalogLoading ? "Loading..." : "Load More Catalog Results"}
                </button>
              ) : null}
            </section>
          </>
        ) : null}

        {activeTab === "onboarding" ? (
          <>
            <section className="feed-section">
              <div className="section-head">
                <h3>AI Onboarding</h3>
                <span>Create a new DailyLens profile and initialize preferences</span>
              </div>
              <div className="onboarding-grid">
                <div className="panel onboarding-form">
                  <div className="onboarding-progress">
                    <div className="onboarding-progress-head">
                      <strong>Profile readiness</strong>
                      <span>{onboardingReadiness}%</span>
                    </div>
                    <div className="meter">
                      <div style={{ width: `${onboardingReadiness}%` }} />
                    </div>
                  </div>
                <div className="search-row">
                  <input placeholder="Name" value={onboardingName} onChange={(e) => setOnboardingName(e.target.value)} />
                  <select value={onboardingRole} onChange={(e) => setOnboardingRole(e.target.value)}>
                      <option>AI Engineer</option>
                      <option>Data Scientist</option>
                      <option>ML Engineer</option>
                      <option>Research Engineer</option>
                    <option>MLOps Engineer</option>
                  </select>
                </div>
                <div className="search-row">
                  <select value={onboardingFocusMode} onChange={(e) => setOnboardingFocusMode(e.target.value as "strict" | "balanced" | "discovery")}>
                    <option value="strict">Strict AI focus</option>
                    <option value="balanced">Balanced focus</option>
                    <option value="discovery">Discovery focus</option>
                  </select>
                  <div className="focus-preview">
                    Core {Math.round(((onboardingFocusMode === "strict" ? 0.85 : onboardingFocusMode === "discovery" ? 0.55 : 0.7) * 100))}%
                    {" • "}
                    Adjacent {Math.round(((onboardingFocusMode === "strict" ? 0.12 : onboardingFocusMode === "discovery" ? 0.25 : 0.2) * 100))}%
                    {" • "}
                    Frontier {Math.round(((onboardingFocusMode === "strict" ? 0.03 : onboardingFocusMode === "discovery" ? 0.2 : 0.1) * 100))}%
                  </div>
                </div>
                <div className="search-row">
                    <input
                      placeholder="Primary goal"
                      value={onboardingGoal}
                      onChange={(e) => setOnboardingGoal(e.target.value)}
                    />
                    <input
                      placeholder="Referral code (optional)"
                      value={onboardingReferralCode}
                      onChange={(e) => setOnboardingReferralCode(e.target.value)}
                    />
                  </div>
                  <div className="chip-row">
                    {AI_INTERESTS.map((interest) => (
                      <button
                        key={interest}
                        className={`tab-btn ${onboardingInterests.includes(interest) ? "active" : ""}`}
                        onClick={() => toggleInterest(interest)}
                        type="button"
                      >
                        {interest}
                      </button>
                    ))}
                  </div>
                  <button className="refresh-btn" disabled={onboardingLoading} onClick={() => void submitOnboarding()}>
                    {onboardingLoading ? "Creating profile..." : "Complete Onboarding"}
                  </button>
                </div>

                <aside className="panel onboarding-guide">
                  <p className="panel-title">How onboarding works</p>
                  <ul className="note-list">
                    <li>Pick role + interests to initialize your recommendation profile.</li>
                    <li>We balance relevance with discovery so new domains are still surfaced.</li>
                    <li>Your referral code unlocks renewal discounts as teammates join.</li>
                    <li>After signup, your feed loads immediately with AI-focused stories.</li>
                  </ul>
                </aside>
              </div>
            </section>
          </>
        ) : null}

        <div ref={sentinelRef} className="sentinel" />
      </main>

      {profileOpen ? <button className="drawer-backdrop" onClick={() => setProfileOpen(false)} aria-label="Close profile" /> : null}
      <aside className={`profile-drawer ${profileOpen ? "open" : ""}`}>
        <div className="profile-header">
          <h3>Profile</h3>
          <button className="small-btn ghost" onClick={() => setProfileOpen(false)}>Close</button>
        </div>
        <div className="tab-row profile-tabs">
          <button className={`tab-btn ${profileTab === "account" ? "active" : ""}`} onClick={() => setProfileTab("account")}>Account</button>
          <button className={`tab-btn ${profileTab === "preferences" ? "active" : ""}`} onClick={() => setProfileTab("preferences")}>Preferences</button>
          <button className={`tab-btn ${profileTab === "system" ? "active" : ""}`} onClick={() => setProfileTab("system")}>System</button>
        </div>

        {profileTab === "account" ? (
          <>
            <div className="panel">
              <p className="panel-title">Active Reader</p>
              <select value={currentUser} onChange={(e) => handleUserChange(e.target.value)}>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name} ({u.id})
                  </option>
                ))}
              </select>
              <button
                className="refresh-btn"
                disabled={refreshing}
                onClick={async () => {
                  setRefreshing(true);
                  try {
                    const r = await refreshContent();
                    setStatus(`Refreshed ${r.article_count} posts at ${new Date(r.refreshed_at).toLocaleTimeString()}`);
                    setOffset(0);
                    setItems([]);
                    setHasMore(true);
                    await hydrateFeed(true);
                  } catch (error) {
                    setStatus(`Refresh failed: ${(error as Error).message}`);
                  } finally {
                    setRefreshing(false);
                  }
                }}
              >
                {refreshing ? "Refreshing..." : "Refresh News Pool"}
              </button>
            </div>
            <div className="panel">
              <p className="panel-title">Plan and Usage</p>
              <p className="usage-line">Plan: {(entitlement?.tier ?? currentUserObj?.tier ?? "free").toUpperCase()}</p>
              <p className="usage-line">
                {entitlement?.monthly_limit === null
                  ? `${entitlement?.monthly_used ?? 0} posts used this month`
                  : `${entitlement?.monthly_used ?? 0}/${entitlement?.monthly_limit ?? 0} posts used this month`}
              </p>
              <p className="usage-line">Referral code: {entitlement?.referral_code ?? currentUserObj?.referral_code ?? "n/a"}</p>
              <p className="usage-line">Renewal discount: {entitlement?.renewal_discount_percent ?? currentUserObj?.renewal_discount_percent ?? 0}%</p>
              <button className="small-btn" onClick={() => void simulateReferral()} disabled={referralLoading || !currentUser}>
                {referralLoading ? "Processing..." : "Simulate Referral Signup"}
              </button>
            </div>
          </>
        ) : null}

        {profileTab === "preferences" ? (
          <>
            <section className="focus-bar">
              <p className="panel-title">Recommendation Scenario</p>
              <div className="focus-controls">
                {FOCUS_OPTIONS.map((mode) => (
                  <button
                    key={mode}
                    className={`tab-btn ${currentFocusMode === mode ? "active" : ""}`}
                    onClick={() => void handleFocusModeChange(mode)}
                    disabled={focusLoading || !currentUser}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            </section>
            <div className="panel">
              <p className="panel-title">Topic Buckets</p>
              <ul className="pull-list">
                {Object.entries(topicBuckets).sort((a, b) => a[0].localeCompare(b[0])).map(([subject, bucket]) => (
                  <li key={subject}><span>{subject}</span><strong>{bucket}</strong></li>
                ))}
              </ul>
            </div>
            <div className="panel">
              <p className="panel-title">Exploration Priorities</p>
              <section className="chip-row">
                {Object.entries(explorationScores)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 12)
                  .map(([subject, value]) => (
                    <div className="topic-chip" key={subject}>
                      <span>{subject}</span>
                      <small>Exploration {pct(value)}</small>
                    </div>
                  ))}
              </section>
            </div>
            <div className="panel">
              <p className="panel-title">Preference Intensity</p>
              <ul className="metrics-list">
                {Object.entries(affinity)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 10)
                  .map(([subject, value]) => (
                    <li key={subject}>
                      <span>{subject}</span>
                      <div className="meter">
                        <div style={{ width: pct(value) }} />
                      </div>
                      <strong>{pct(value)}</strong>
                    </li>
                  ))}
              </ul>
            </div>
            <div className="panel">
              <p className="panel-title">Exploration Coverage</p>
              <ul className="pull-list">
                {Object.entries(pulls)
                  .sort((a, b) => a[1] - b[1])
                  .slice(0, 12)
                  .map(([subject, count]) => (
                    <li key={subject}>
                      <span>{subject}</span>
                      <strong>{count}</strong>
                    </li>
                  ))}
              </ul>
            </div>
          </>
        ) : null}

        {profileTab === "system" ? (
          <>
            <div className="panel">
              <div className="section-head">
                <p className="panel-title">Monitoring</p>
                <button className="small-btn ghost" onClick={() => void fetchMonitoring()} disabled={monitoringLoading}>Refresh</button>
              </div>
              <p className="usage-line">Mode: {monitoring?.runtime_mode ?? "n/a"}</p>
              <p className="usage-line">Event backend: {monitoring?.event_pipeline.queue_backend ?? "n/a"}</p>
              <p className="usage-line">Queue depth: {(monitoring?.event_pipeline.queue_depth ?? -1) >= 0 ? monitoring?.event_pipeline.queue_depth : "n/a"}</p>
              <p className="usage-line">Processed events: {monitoring?.event_pipeline.events_processed ?? 0}</p>
            </div>
            <div className="panel">
              <p className="panel-title">Event Pipeline</p>
              <ul className="pull-list">
                <li><span>Backend</span><strong>{monitoring?.event_pipeline.queue_backend ?? "n/a"}</strong></li>
                <li><span>Queue depth</span><strong>{(monitoring?.event_pipeline.queue_depth ?? -1) >= 0 ? monitoring?.event_pipeline.queue_depth : "n/a"}</strong></li>
                <li><span>Processed</span><strong>{monitoring?.event_pipeline.events_processed ?? 0}</strong></li>
                <li><span>Failed</span><strong>{monitoring?.event_pipeline.events_failed ?? 0}</strong></li>
                <li><span>Dropped</span><strong>{monitoring?.event_pipeline.events_dropped ?? 0}</strong></li>
                <li><span>Published</span><strong>{monitoring?.event_pipeline.events_published ?? 0}</strong></li>
                <li><span>Publish Fail</span><strong>{monitoring?.event_pipeline.events_publish_failed ?? 0}</strong></li>
              </ul>
            </div>
            <div className="panel">
              <p className="panel-title">Feed Serving</p>
              <ul className="pull-list">
                <li><span>Cache entries</span><strong>{monitoring?.feed_serving.feed_cache_entries ?? 0}</strong></li>
                <li><span>Cache hits</span><strong>{monitoring?.feed_serving.feed_cache_hits ?? 0}</strong></li>
                <li><span>Cache misses</span><strong>{monitoring?.feed_serving.feed_cache_misses ?? 0}</strong></li>
                <li><span>Precomputed users</span><strong>{monitoring?.feed_serving.precomputed_user_bundles ?? 0}</strong></li>
              </ul>
            </div>
            <div className="panel">
              <p className="panel-title">User Mix</p>
              <ul className="pull-list">
                {Object.entries(monitoring?.user_mix ?? {}).map(([tier, count]) => (
                  <li key={tier}><span>{tier}</span><strong>{count}</strong></li>
                ))}
              </ul>
            </div>
            <div className="panel">
              <p className="panel-title">ARRRR Snapshot</p>
              <ul className="pull-list">
                {Object.entries(monitoring?.arrrr_metrics ?? {}).map(([metric, value]) => (
                  <li key={metric}><span>{metric}</span><strong>{value}</strong></li>
                ))}
              </ul>
            </div>
            <div className="panel">
              <p className="panel-title">Endpoint Metrics</p>
              <div className="endpoint-grid">
                {Object.entries(monitoring?.traffic_metrics ?? {}).map(([endpoint, metric]) => (
                  <article key={endpoint} className="endpoint-card">
                    <h4>{endpoint}</h4>
                    <p>Count: {metric.count}</p>
                    <p>Errors: {metric.errors}</p>
                    <p>Avg latency: {metric.avg_latency_ms} ms</p>
                    <p>P95 latency: {metric.p95_latency_ms} ms</p>
                    <p>Cache hits: {metric.cache_hit_count}</p>
                  </article>
                ))}
              </div>
            </div>
            <div className="panel">
              <p className="panel-title">Recent Logs</p>
              <div className="log-list compact-log-list">
                {(monitoring?.recent_logs ?? []).slice(0, 24).map((entry, idx) => (
                  <pre key={idx}>{JSON.stringify(entry, null, 2)}</pre>
                ))}
              </div>
            </div>
          </>
        ) : null}
      </aside>
    </div>
  );
}
