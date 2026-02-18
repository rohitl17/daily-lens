export type User = {
  id: string;
  name: string;
  tier: "free" | "silver" | "gold";
  role?: string;
  focus_mode?: "strict" | "balanced" | "discovery";
  icp_profile?: boolean;
  referral_code?: string;
  referral_count?: number;
  monthly_limit: number | null;
  monthly_used: number;
  monthly_remaining: number | null;
  renewal_discount_percent?: number;
};

export type FeedItem = {
  id: string;
  title: string;
  subject: string;
  summary: string;
  created_at: string;
  url: string;
  source: string;
  score: number;
  is_sponsored?: boolean;
};

export type Entitlement = {
  tier: "free" | "silver" | "gold";
  monthly_limit: number | null;
  monthly_used: number;
  monthly_remaining: number | null;
  can_consume: boolean;
  ad_enabled: boolean;
  billing_window_start: string;
  referral_code?: string;
  referral_count?: number;
  renewal_discount_percent?: number;
};

export type FeedResponse = {
  items: FeedItem[];
  next_offset: number;
  has_more: boolean;
  subject_affinity: Record<string, number>;
  exploration_subject_scores?: Record<string, number>;
  bandit_subject_scores?: Record<string, number>;
  subject_pull_counts: Record<string, number>;
  feed_focus_mode?: "strict" | "balanced" | "discovery";
  topic_buckets?: Record<string, "core" | "adjacent" | "frontier">;
  target_mix?: Record<string, number>;
  entitlement: Entitlement;
  message?: string;
};

export type ExploreResponse = {
  items: FeedItem[];
  next_offset: number;
  has_more: boolean;
  total: number;
  subjects: string[];
  entitlement: Entitlement;
  message?: string;
};

export type InteractionAction = "view" | "like" | "save" | "share" | "skip";

export type MonitoringDashboard = {
  runtime_mode: string;
  data_layer_plan: Record<string, string>;
  event_pipeline: {
    queue_backend: string;
    queue_depth: number;
    events_processed: number;
    events_failed: number;
    events_dropped: number;
    events_published?: number;
    events_publish_failed?: number;
    kafka_bootstrap_servers?: string;
    kafka_topic?: string;
  };
  feed_serving: {
    feed_cache_entries: number;
    feed_cache_ttl_seconds: number;
    feed_cache_hits: number;
    feed_cache_misses: number;
    precomputed_user_bundles: number;
  };
  rate_limits: {
    window_seconds: number;
    limits_per_window: Record<string, number>;
  };
  traffic_metrics: Record<
    string,
    {
      count: number;
      errors: number;
      avg_latency_ms: number;
      p95_latency_ms: number;
      cache_hit_count: number;
    }
  >;
  user_mix: Record<string, number>;
  arrrr_metrics?: Record<string, number>;
  recent_logs: Array<Record<string, unknown>>;
};

export type OnboardingPayload = {
  name: string;
  role: string;
  interests: string[];
  goal?: string;
  referralCode?: string;
  focusMode?: "strict" | "balanced" | "discovery";
};

export type OnboardingResponse = {
  ok: boolean;
  user: User;
  entitlement: Entitlement;
  message: string;
};
