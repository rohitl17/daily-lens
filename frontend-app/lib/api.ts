import type { Entitlement, ExploreResponse, FeedResponse, InteractionAction, MonitoringDashboard, OnboardingPayload, OnboardingResponse, User } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers ?? {}),
    },
    ...options,
    cache: "no-store",
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${detail}`);
  }

  return (await res.json()) as T;
}

export async function getHealth(): Promise<{ status: string; article_count: number }> {
  return request("/health");
}

export async function getUsers(): Promise<User[]> {
  return request("/api/users");
}

export async function refreshContent(): Promise<{
  ok: boolean;
  article_count: number;
  user_count: number;
  interaction_count: number;
  refreshed_at: string;
}> {
  return request("/api/refresh", { method: "POST" });
}

export async function getFeed(userId: string, offset: number, limit: number): Promise<FeedResponse> {
  return request("/api/feed", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, offset, limit }),
  });
}

export async function exploreCatalog(params: {
  userId: string;
  query?: string;
  subject?: string;
  includeSeen?: boolean;
  offset?: number;
  limit?: number;
}): Promise<ExploreResponse> {
  return request("/api/explore", {
    method: "POST",
    body: JSON.stringify({
      user_id: params.userId,
      query: params.query ?? "",
      subject: params.subject ?? "",
      include_seen: params.includeSeen ?? false,
      offset: params.offset ?? 0,
      limit: params.limit ?? 20,
    }),
  });
}

export async function sendInteraction(params: {
  userId: string;
  articleId: string;
  action: InteractionAction;
  dwellSeconds: number;
}): Promise<{ ok: boolean; entitlement?: Entitlement }> {
  return request("/api/interactions", {
    method: "POST",
    body: JSON.stringify({
      user_id: params.userId,
      article_id: params.articleId,
      action: params.action,
      dwell_seconds: params.dwellSeconds,
    }),
  });
}

export async function getMonitoringDashboard(): Promise<MonitoringDashboard> {
  return request("/api/monitoring/dashboard");
}

export async function onboardUser(payload: OnboardingPayload): Promise<OnboardingResponse> {
  return request("/api/users/onboard", {
    method: "POST",
    body: JSON.stringify({
      name: payload.name,
      role: payload.role,
      interests: payload.interests,
      goal: payload.goal ?? "",
      referral_code: payload.referralCode ?? "",
      focus_mode: payload.focusMode ?? "balanced",
    }),
  });
}

export async function updateUserFocusMode(params: {
  userId: string;
  focusMode: "strict" | "balanced" | "discovery";
}): Promise<{ ok: boolean; user_id: string; focus_mode: "strict" | "balanced" | "discovery" }> {
  return request("/api/users/focus", {
    method: "POST",
    body: JSON.stringify({
      user_id: params.userId,
      focus_mode: params.focusMode,
    }),
  });
}

export async function simulateReferralSignup(params: {
  inviterUserId: string;
  inviteeName: string;
  inviteeRole: string;
  interests?: string[];
}): Promise<{
  ok: boolean;
  inviter_user_id: string;
  inviter_referral_code: string;
  inviter_referral_count: number;
  inviter_renewal_discount_percent: number;
  new_user: User;
}> {
  return request("/api/referrals/simulate-signup", {
    method: "POST",
    body: JSON.stringify({
      inviter_user_id: params.inviterUserId,
      invitee_name: params.inviteeName,
      invitee_role: params.inviteeRole,
      interests: params.interests ?? [],
    }),
  });
}
