from __future__ import annotations

import math
import random
import re
import html
import json
import logging
import os
import time
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Literal, Optional, Set, Tuple
from urllib.parse import quote_plus
from urllib.request import urlopen
import xml.etree.ElementTree as ET
import queue

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from kafka import KafkaConsumer, KafkaProducer
except Exception:
    KafkaConsumer = None
    KafkaProducer = None

try:
    from pymongo import MongoClient
except Exception:
    MongoClient = None


SUBJECTS = [
    "Engineering",
    "Business",
    "Sales",
    "AI",
    "Fitness",
    "Finance",
    "Marketing",
    "Product",
    "Science",
    "Cybersecurity",
    "Design",
    "Miscellaneous",
]
AI_CORE_SUBJECTS = {"AI", "Engineering", "Science", "Cybersecurity"}
AI_ADJACENT_SUBJECTS = {"Product", "Design", "Finance", "Marketing"}
AI_FRONTIER_SUBJECTS = {"Business", "Sales", "Fitness", "Miscellaneous"}
FOCUS_MODES = {"strict", "balanced", "discovery"}
INTERACTION_ACTIONS = ["view", "like", "save", "share", "skip"]
TARGET_ARTICLE_COUNT = 100
POST_LIMITS_PER_MONTH = {"free": 5, "silver": 50, "gold": None}
SPONSORED_CARDS = [
    {
        "title": "Sponsored: Build AI Agents Faster",
        "summary": "Ship production-ready agent workflows with managed tooling and observability.",
        "url": "https://example.com/ai-agents",
        "source": "VectorCloud",
    },
    {
        "title": "Sponsored: Learn Product Strategy in 30 Days",
        "summary": "Structured cohort for PMs covering roadmap, discovery, and growth loops.",
        "url": "https://example.com/product-strategy",
        "source": "ProductCraft Pro",
    },
    {
        "title": "Sponsored: Zero-Trust Security for Startups",
        "summary": "Harden endpoints, identity, and secrets without enterprise overhead.",
        "url": "https://example.com/zero-trust",
        "source": "SafeStack",
    },
]

TOPIC_QUERIES = {
    "Engineering": "engineering software development",
    "Business": "business strategy markets",
    "Sales": "sales leadership b2b",
    "AI": "artificial intelligence machine learning",
    "Fitness": "fitness health training",
    "Finance": "finance investing personal finance",
    "Marketing": "marketing growth brand strategy",
    "Product": "product management roadmap user research",
    "Science": "science discoveries research",
    "Cybersecurity": "cybersecurity security threats privacy",
    "Design": "design ux ui product design",
    "Miscellaneous": "workplace productivity lifestyle",
}


@dataclass
class User:
    id: str
    name: str
    tier: Literal["free", "silver", "gold"]
    role: str = "AI Engineer"
    onboarding_completed: bool = False
    referral_code: str = ""
    referral_count: int = 0
    referred_by: Optional[str] = None
    focus_mode: Literal["strict", "balanced", "discovery"] = "balanced"


@dataclass
class Article:
    id: str
    title: str
    subject: str
    summary: str
    created_at: datetime
    url: str
    source: str


class Interaction(BaseModel):
    user_id: str
    article_id: str
    action: Literal["view", "like", "save", "share", "skip"]
    dwell_seconds: float = Field(ge=0, le=3600)
    ts: datetime


class FeedRequest(BaseModel):
    user_id: str
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=25)


class ExploreRequest(BaseModel):
    user_id: str
    query: Optional[str] = None
    subject: Optional[str] = None
    include_seen: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)


class InteractionRequest(BaseModel):
    user_id: str
    article_id: str
    action: Literal["view", "like", "save", "share", "skip"]
    dwell_seconds: float = Field(default=0, ge=0, le=3600)


class OnboardingRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    role: str = Field(min_length=2, max_length=80)
    interests: List[str] = Field(default_factory=list)
    goal: str = Field(default="")
    referral_code: Optional[str] = None
    focus_mode: Literal["strict", "balanced", "discovery"] = "balanced"


class ReferralSignupRequest(BaseModel):
    inviter_user_id: str
    invitee_name: str = Field(min_length=2, max_length=80)
    invitee_role: str = Field(default="AI Engineer")
    interests: List[str] = Field(default_factory=list)


class UserFocusRequest(BaseModel):
    user_id: str
    focus_mode: Literal["strict", "balanced", "discovery"]


app = FastAPI(title="DailyLens API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

users: List[User] = []
articles: List[Article] = []
interactions: List[Interaction] = []
seen_articles: Dict[str, Set[str]] = {}

# v2-scale simulation primitives (local/laptop friendly):
# - feed page cache (TTL)
# - stream event queue + async processor
# - user feature cache
# - endpoint metrics + recent logs
# - per-user request rate limiting
FEED_CACHE_TTL_SECONDS = 20
PRECOMPUTE_TTL_SECONDS = 30
MAX_FEED_ARTICLE_AGE_DAYS = int(os.getenv("MAX_FEED_ARTICLE_AGE_DAYS", "30"))
INTERACTION_HALF_LIFE_DAYS = float(os.getenv("INTERACTION_HALF_LIFE_DAYS", "21"))
INTERACTION_MAX_AGE_DAYS = int(os.getenv("INTERACTION_MAX_AGE_DAYS", "180"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMITS_PER_WINDOW = {
    "/api/feed": int(os.getenv("RATE_LIMIT_FEED_PER_WINDOW", "600")),
    "/api/explore": int(os.getenv("RATE_LIMIT_EXPLORE_PER_WINDOW", "300")),
}

feed_page_cache: Dict[str, Tuple[float, dict]] = {}
feed_cache_hits = 0
feed_cache_misses = 0

precomputed_rank_cache: Dict[str, dict] = {}
user_state_version: Dict[str, int] = {}

rate_limit_buckets: Dict[str, List[float]] = {}

event_queue: "queue.Queue[dict]" = queue.Queue(maxsize=10000)
event_processor_thread: Optional[threading.Thread] = None
event_processor_running = False
event_processor_lock = threading.Lock()
events_processed = 0
events_failed = 0
event_queue_dropped = 0

EVENT_PIPELINE_BACKEND = os.getenv("EVENT_PIPELINE_BACKEND", "local").strip().lower()
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092").strip()
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "user-interactions").strip()
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "dailylens-ranker").strip()
KAFKA_POLL_TIMEOUT_MS = int(os.getenv("KAFKA_POLL_TIMEOUT_MS", "1000"))

kafka_producer = None
kafka_consumer_thread: Optional[threading.Thread] = None
kafka_consumer_running = False
kafka_consumer_lock = threading.Lock()
events_published = 0
events_publish_failed = 0
event_pipeline_mode = "local"

user_subject_stream_stats: Dict[str, Dict[str, Dict[str, float]]] = {}

DATA_BACKEND = os.getenv("DATA_BACKEND", "memory").strip().lower()
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017").strip()
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "dailylens").strip()
mongo_client = None
mongo_db = None
data_backend_mode = "memory"
mongo_write_failures = 0

ARRRR_METRICS = {
    "acquisition_signups": 0,
    "activation_onboarded": 0,
    "referrals_sent": 0,
    "referral_signups": 0,
    "revenue_discount_events": 0,
}

endpoint_metrics: Dict[str, dict] = {}
recent_logs: deque = deque(maxlen=300)

logger = logging.getLogger("dailylens")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _clean_text(text: str) -> str:
    cleaned = html.unescape(text or "")
    replacements = {
        "â€™": "'",
        "â€œ": '"',
        "â€\x9d": '"',
        "â€”": "-",
        "â€“": "-",
        "â€¦": "...",
        "Â": "",
        "•": "-",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[^\x20-\x7E]", "", cleaned)
    return cleaned


def _log_event(event: str, **kwargs: object) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **kwargs,
    }
    recent_logs.appendleft(payload)
    logger.info(json.dumps(payload))


def _mongo_available() -> bool:
    return MongoClient is not None


def _mongo_init() -> bool:
    global mongo_client, mongo_db
    if not _mongo_available():
        return False
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1200, connectTimeoutMS=1200)
        mongo_client.admin.command("ping")
        mongo_db = mongo_client[MONGO_DB_NAME]
        return True
    except Exception as ex:
        _log_event("mongo_init_failed", error=str(ex))
        mongo_client = None
        mongo_db = None
        return False


def _mongo_collection(name: str):
    if mongo_db is None:
        return None
    return mongo_db[name]


def _coerce_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def _persist_snapshot_to_mongo() -> None:
    global mongo_write_failures
    if data_backend_mode != "mongo":
        return
    try:
        users_col = _mongo_collection("users")
        articles_col = _mongo_collection("articles")
        interactions_col = _mongo_collection("interactions")
        meta_col = _mongo_collection("meta")
        if users_col is None or articles_col is None or interactions_col is None or meta_col is None:
            return

        users_col.delete_many({})
        users_col.insert_many(
            [
                {
                    "id": u.id,
                    "name": u.name,
                    "tier": u.tier,
                    "role": u.role,
                    "focus_mode": u.focus_mode,
                    "onboarding_completed": u.onboarding_completed,
                    "referral_code": u.referral_code,
                    "referral_count": u.referral_count,
                    "referred_by": u.referred_by,
                }
                for u in users
            ]
        )

        articles_col.delete_many({})
        articles_col.insert_many(
            [
                {
                    "id": a.id,
                    "title": a.title,
                    "subject": a.subject,
                    "summary": a.summary,
                    "created_at": a.created_at,
                    "url": a.url,
                    "source": a.source,
                }
                for a in articles
            ]
        )

        interactions_col.delete_many({})
        if interactions:
            interactions_col.insert_many(
                [
                    {
                        "user_id": i.user_id,
                        "article_id": i.article_id,
                        "action": i.action,
                        "dwell_seconds": i.dwell_seconds,
                        "ts": i.ts,
                    }
                    for i in interactions
                ]
            )
        meta_col.update_one(
            {"_id": "runtime"},
            {
                "$set": {
                    "updated_at": datetime.now(timezone.utc),
                    "user_state_version": user_state_version,
                }
            },
            upsert=True,
        )
    except Exception as ex:
        mongo_write_failures += 1
        _log_event("mongo_persist_snapshot_failed", error=str(ex))


def _persist_interaction_to_mongo(event: Interaction) -> None:
    global mongo_write_failures
    if data_backend_mode != "mongo":
        return
    try:
        interactions_col = _mongo_collection("interactions")
        if interactions_col is None:
            return
        interactions_col.insert_one(
            {
                "user_id": event.user_id,
                "article_id": event.article_id,
                "action": event.action,
                "dwell_seconds": event.dwell_seconds,
                "ts": event.ts,
            }
        )
    except Exception as ex:
        mongo_write_failures += 1
        _log_event("mongo_persist_interaction_failed", error=str(ex))


def _persist_articles_to_mongo(new_articles: List[Article]) -> None:
    global mongo_write_failures
    if data_backend_mode != "mongo" or not new_articles:
        return
    try:
        articles_col = _mongo_collection("articles")
        if articles_col is None:
            return
        existing = set(articles_col.distinct("id", {"id": {"$in": [a.id for a in new_articles]}}))
        payload = [
            {
                "id": a.id,
                "title": a.title,
                "subject": a.subject,
                "summary": a.summary,
                "created_at": a.created_at,
                "url": a.url,
                "source": a.source,
            }
            for a in new_articles
            if a.id not in existing
        ]
        if payload:
            articles_col.insert_many(payload)
    except Exception as ex:
        mongo_write_failures += 1
        _log_event("mongo_persist_articles_failed", error=str(ex))


def _load_state_from_mongo() -> bool:
    global users, articles, interactions, seen_articles, feed_page_cache, precomputed_rank_cache
    if data_backend_mode != "mongo":
        return False
    try:
        users_col = _mongo_collection("users")
        articles_col = _mongo_collection("articles")
        interactions_col = _mongo_collection("interactions")
        if users_col is None or articles_col is None or interactions_col is None:
            return False

        user_docs = list(users_col.find({}, {"_id": 0}))
        article_docs = list(articles_col.find({}, {"_id": 0}))
        interaction_docs = list(interactions_col.find({}, {"_id": 0}))
        if not user_docs or not article_docs:
            return False

        users = [
            User(
                id=str(d["id"]),
                name=str(d["name"]),
                tier=str(d["tier"]),
                role=str(d.get("role", "AI Engineer")),
                focus_mode=_normalize_focus_mode(str(d.get("focus_mode", "balanced"))),
                onboarding_completed=bool(d.get("onboarding_completed", False)),
                referral_code=str(d.get("referral_code", f"DL-{str(d['id']).upper()}")),
                referral_count=int(d.get("referral_count", 0)),
                referred_by=str(d.get("referred_by")) if d.get("referred_by") else None,
            )
            for d in user_docs
        ]
        articles = [
            Article(
                id=str(d["id"]),
                title=str(d.get("title", "")),
                subject=str(d.get("subject", "Miscellaneous")),
                summary=str(d.get("summary", "")),
                created_at=_coerce_dt(d.get("created_at")),
                url=str(d.get("url", "")),
                source=str(d.get("source", "Unknown")),
            )
            for d in article_docs
        ]
        interactions = [
            Interaction(
                user_id=str(d.get("user_id", "")),
                article_id=str(d.get("article_id", "")),
                action=str(d.get("action", "view")),
                dwell_seconds=float(d.get("dwell_seconds", 0.0)),
                ts=_coerce_dt(d.get("ts")),
            )
            for d in interaction_docs
        ]

        seen_articles = {u.id: set() for u in users}
        for it in interactions:
            seen_articles.setdefault(it.user_id, set()).add(it.article_id)

        for user in users:
            user_state_version[user.id] = 0
        feed_page_cache = {}
        precomputed_rank_cache = {}
        _replay_stream_stats_from_history()
        return True
    except Exception as ex:
        _log_event("mongo_load_state_failed", error=str(ex))
        return False


def _record_endpoint_metric(endpoint: str, latency_ms: float, ok: bool, cache_hit: Optional[bool] = None) -> None:
    m = endpoint_metrics.setdefault(
        endpoint,
        {"count": 0, "errors": 0, "latency_total_ms": 0.0, "latency_p95_buffer": []},
    )
    m["count"] += 1
    if not ok:
        m["errors"] += 1
    m["latency_total_ms"] += latency_ms
    m["latency_p95_buffer"].append(latency_ms)
    if len(m["latency_p95_buffer"]) > 400:
        m["latency_p95_buffer"] = m["latency_p95_buffer"][-400:]
    if cache_hit is not None:
        m["cache_hit_count"] = m.get("cache_hit_count", 0) + (1 if cache_hit else 0)


def _enforce_rate_limit(user_id: str, endpoint: str) -> None:
    # Sliding-window limiter keyed by endpoint+user.
    # We keep only timestamps inside the active window and reject once limit is reached.
    limit = RATE_LIMITS_PER_WINDOW.get(endpoint)
    if limit is None:
        return
    now_ts = time.time()
    key = f"{endpoint}:{user_id}"
    bucket = rate_limit_buckets.get(key, [])
    cutoff = now_ts - RATE_LIMIT_WINDOW_SECONDS
    bucket = [x for x in bucket if x >= cutoff]
    if len(bucket) >= limit:
        oldest = bucket[0] if bucket else now_ts
        retry_after = max(1, int((oldest + RATE_LIMIT_WINDOW_SECONDS) - now_ts) + 1)
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Rate limit exceeded. Please retry shortly.",
                "endpoint": endpoint,
                "limit_per_minute": limit,
                "retry_after_seconds": retry_after,
            },
        )
    bucket.append(now_ts)
    rate_limit_buckets[key] = bucket


def _cache_key_feed(user_id: str, offset: int, limit: int, version: int) -> str:
    return f"{user_id}:{offset}:{limit}:v{version}"


def _invalidate_user_caches(user_id: str) -> None:
    precomputed_rank_cache.pop(user_id, None)
    for key in list(feed_page_cache.keys()):
        if key.startswith(f"{user_id}:"):
            feed_page_cache.pop(key, None)


def _kafka_available() -> bool:
    return KafkaProducer is not None and KafkaConsumer is not None


def _encode_event_payload(event: dict) -> bytes:
    return json.dumps(event, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _decode_event_payload(payload: bytes) -> dict:
    return json.loads(payload.decode("utf-8"))


def _process_stream_event(event: dict) -> None:
    user_id = str(event.get("user_id", ""))
    article_id = str(event.get("article_id", ""))
    action = str(event.get("action", "view"))
    dwell_seconds = float(event.get("dwell_seconds", 0.0))
    if not user_id or not article_id:
        return
    article_subject = {a.id: a.subject for a in articles}
    subject = article_subject.get(article_id)
    if not subject:
        return

    per_user = user_subject_stream_stats.setdefault(user_id, {})
    stats = per_user.setdefault(subject, {"count": 0.0, "reward_sum": 0.0, "reward_mean": 0.0})
    stats["count"] += 1.0
    reward = _interaction_reward(action, dwell_seconds)
    stats["reward_sum"] += reward
    stats["reward_mean"] = stats["reward_sum"] / max(stats["count"], 1.0)


def _event_worker() -> None:
    global events_processed, events_failed, event_processor_running
    while event_processor_running:
        try:
            event = event_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _process_stream_event(event)
            events_processed += 1
        except Exception as ex:
            events_failed += 1
            _log_event("stream_process_error", error=str(ex))
        finally:
            event_queue.task_done()


def _kafka_event_worker() -> None:
    global events_processed, events_failed, kafka_consumer_running
    consumer = None
    try:
        consumer = KafkaConsumer(
            KAFKA_TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=KAFKA_GROUP_ID,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=_decode_event_payload,
        )
        _log_event("kafka_consumer_started", topic=KAFKA_TOPIC, bootstrap=KAFKA_BOOTSTRAP_SERVERS)
        while kafka_consumer_running:
            polled = consumer.poll(timeout_ms=KAFKA_POLL_TIMEOUT_MS, max_records=200)
            if not polled:
                continue
            for records in polled.values():
                for record in records:
                    try:
                        event = record.value if isinstance(record.value, dict) else {}
                        _process_stream_event(event)
                        events_processed += 1
                    except Exception as ex:
                        events_failed += 1
                        _log_event("kafka_event_process_error", error=str(ex))
    except Exception as ex:
        _log_event("kafka_consumer_fatal", error=str(ex))
    finally:
        if consumer is not None:
            try:
                consumer.close()
            except Exception:
                pass
        _log_event("kafka_consumer_stopped")


def _publish_stream_event(event: dict) -> None:
    global events_published, events_publish_failed, event_queue_dropped

    # Prefer Kafka when configured; degrade to local queue so user actions are never dropped
    # just because optional infra is unavailable.
    if event_pipeline_mode == "kafka" and kafka_producer is not None:
        try:
            future = kafka_producer.send(KAFKA_TOPIC, event)
            future.get(timeout=1.5)
            events_published += 1
            return
        except Exception as ex:
            events_publish_failed += 1
            _log_event("kafka_publish_failed_fallback_local", error=str(ex))

    try:
        event_queue.put_nowait(event)
        events_published += 1
    except queue.Full:
        event_queue_dropped += 1


def _start_event_processor() -> None:
    global event_processor_thread, event_processor_running
    with event_processor_lock:
        if event_processor_running:
            return
        event_processor_running = True
        event_processor_thread = threading.Thread(target=_event_worker, name="event-worker", daemon=True)
        event_processor_thread.start()
        _log_event("stream_processor_started")


def _stop_event_processor() -> None:
    global event_processor_running, event_processor_thread
    with event_processor_lock:
        event_processor_running = False
        t = event_processor_thread
        event_processor_thread = None
    if t is not None:
        t.join(timeout=2.0)


def _start_kafka_pipeline() -> bool:
    global kafka_producer, kafka_consumer_thread, kafka_consumer_running
    with kafka_consumer_lock:
        if kafka_consumer_running:
            return True
        try:
            kafka_producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: _encode_event_payload(v),
                linger_ms=25,
                retries=3,
                acks="all",
            )
            kafka_consumer_running = True
            kafka_consumer_thread = threading.Thread(target=_kafka_event_worker, name="kafka-consumer", daemon=True)
            kafka_consumer_thread.start()
            _log_event("kafka_pipeline_started", topic=KAFKA_TOPIC, bootstrap=KAFKA_BOOTSTRAP_SERVERS)
            return True
        except Exception as ex:
            kafka_consumer_running = False
            kafka_producer = None
            _log_event("kafka_pipeline_start_failed", error=str(ex))
            return False


def _stop_kafka_pipeline() -> None:
    global kafka_consumer_running, kafka_consumer_thread, kafka_producer
    with kafka_consumer_lock:
        kafka_consumer_running = False
        t = kafka_consumer_thread
        kafka_consumer_thread = None
        producer = kafka_producer
        kafka_producer = None
    if t is not None:
        t.join(timeout=2.0)
    if producer is not None:
        try:
            producer.flush(timeout=2)
        except Exception:
            pass
        try:
            producer.close()
        except Exception:
            pass


def _replay_stream_stats_from_history() -> None:
    user_subject_stream_stats.clear()
    for event in interactions:
        _process_stream_event(
            {
                "user_id": event.user_id,
                "article_id": event.article_id,
                "action": event.action,
                "dwell_seconds": event.dwell_seconds,
            }
        )


def _parse_pub_date(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _fallback_simulated_articles(start_idx: int, count: int) -> List[Article]:
    rng = random.Random(99)
    now = datetime.now(timezone.utc)
    result: List[Article] = []

    templates = {
        "Engineering": ["System Design", "Backend Architecture", "Frontend Reliability", "APIs at Scale"],
        "Business": ["Market Trends", "Pricing Strategies", "Growth Levers", "Unit Economics"],
        "Sales": ["B2B Pipeline", "Outbound Strategies", "Account Expansion", "Deal Forecasting"],
        "AI": ["LLM Productization", "Model Evaluation", "Agent Workflows", "RAG Patterns"],
        "Fitness": ["Strength Programming", "Mobility Routine", "Recovery Science", "Nutrition Habits"],
        "Finance": ["Interest Rate Outlook", "Portfolio Rebalancing", "Fintech Trends", "Budget Optimization"],
        "Marketing": ["Audience Segmentation", "Content Strategy", "Brand Positioning", "Performance Marketing"],
        "Product": ["Roadmap Prioritization", "Discovery Methods", "Feature Adoption", "Experiment Design"],
        "Science": ["Research Breakthroughs", "Lab Methods", "Health Studies", "Climate Findings"],
        "Cybersecurity": ["Threat Intelligence", "Zero Trust", "Security Operations", "Incident Response"],
        "Design": ["Interaction Patterns", "Design Systems", "User Testing", "Accessibility"],
        "Miscellaneous": ["Work-Life Balance", "Communication", "Career Moves", "Creative Thinking"],
    }

    for idx in range(count):
        n = start_idx + idx
        subject = SUBJECTS[n % len(SUBJECTS)]
        topic = rng.choice(templates[subject])
        result.append(
            Article(
                id=f"a{n + 1}",
                title=f"{topic}: Insight {n + 1}",
                subject=subject,
                summary=f"Fallback generated item for {topic.lower()} in {subject.lower()}.",
                created_at=now - timedelta(days=rng.randint(0, 30), hours=rng.randint(0, 23)),
                url="",
                source="Generated",
            )
        )
    return result


def _fetch_real_articles(target_count: int) -> List[Article]:
    fetched: List[Article] = []
    seen_links: Set[str] = set()
    per_subject_cap = max(8, math.ceil(target_count / len(SUBJECTS)) + 3)

    for subject in SUBJECTS:
        query = quote_plus(TOPIC_QUERIES[subject])
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

        try:
            with urlopen(rss_url, timeout=8) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
        except Exception:
            continue

        items = root.findall("./channel/item")
        count = 0
        for item in items:
            if count >= per_subject_cap or len(fetched) >= target_count:
                break

            title = _clean_text((item.findtext("title") or "").strip())
            link = (item.findtext("link") or "").strip()
            summary = _clean_text(_strip_html(item.findtext("description") or ""))
            pub_date = _parse_pub_date(item.findtext("pubDate"))

            source_node = None
            for child in list(item):
                if child.tag.endswith("source"):
                    source_node = child
                    break
            source = _clean_text((source_node.text or "Unknown") if source_node is not None else "Unknown")

            if not title or not link:
                continue
            if link in seen_links:
                continue

            seen_links.add(link)
            fetched.append(
                Article(
                    id=f"a{len(fetched) + 1}",
                    title=title,
                    subject=subject,
                    summary=summary[:300] if summary else _clean_text(f"Recent article about {subject.lower()}."),
                    created_at=pub_date,
                    url=link,
                    source=source,
                )
            )
            count += 1

    if len(fetched) < target_count:
        fetched.extend(_fallback_simulated_articles(len(fetched), target_count - len(fetched)))

    return fetched[:target_count]


def _seed_data() -> None:
    global users, articles, interactions, seen_articles, feed_page_cache, precomputed_rank_cache

    rng = random.Random(42)
    now = datetime.now(timezone.utc)

    users = [
        User(id="u1", name="Ava", tier="free", role="ML Engineer"),
        User(id="u2", name="Noah", tier="silver", role="Data Scientist"),
        User(id="u3", name="Mia", tier="gold", role="AI Research Engineer"),
        User(id="u4", name="Liam", tier="silver", role="MLOps Engineer"),
        User(id="u5", name="Sophia", tier="free", role="AI Product Engineer"),
    ]
    for user in users:
        user.onboarding_completed = True
        user.referral_code = _make_referral_code(user.id)
        user.referral_count = 0
        user.referred_by = None

    articles = _fetch_real_articles(TARGET_ARTICLE_COUNT)
    seen_articles = {u.id: set() for u in users}

    preferred_subjects = {
        "u1": ["Engineering", "AI", "Cybersecurity"],
        "u2": ["AI", "Science", "Finance"],
        "u3": ["AI", "Science", "Engineering"],
        "u4": ["Engineering", "Product", "Cybersecurity"],
        "u5": ["AI", "Product", "Design"],
    }

    interactions = []
    for user in users:
        user_pool = articles.copy()
        rng.shuffle(user_pool)
        initial_count = rng.randint(26, 40)

        for article in user_pool[:initial_count]:
            boosted = article.subject in preferred_subjects[user.id]
            action = _sample_action(rng, boosted)
            dwell = _sample_dwell_seconds(rng, action, boosted)
            ts = now - timedelta(days=rng.randint(35, 120), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))

            interactions.append(
                Interaction(
                    user_id=user.id,
                    article_id=article.id,
                    action=action,
                    dwell_seconds=dwell,
                    ts=ts,
                )
            )
            seen_articles[user.id].add(article.id)

    # Simulate current-month usage by tier for monetization behavior.
    monthly_targets = {
        "u1": 2,   # free
        "u2": 18,  # silver
        "u3": 28,  # gold
        "u4": 37,  # silver
        "u5": 4,   # free
    }
    for user in users:
        target = monthly_targets.get(user.id, 0)
        if target <= 0:
            continue
        user_events = [x for x in interactions if x.user_id == user.id]
        rng.shuffle(user_events)
        for idx, event in enumerate(user_events[:target]):
            event.ts = now - timedelta(days=rng.randint(1, 24), hours=rng.randint(0, 23), minutes=idx % 59)

    for user in users:
        user_state_version[user.id] = 0

    feed_page_cache = {}
    precomputed_rank_cache = {}
    _replay_stream_stats_from_history()


def _sample_action(rng: random.Random, boosted: bool) -> str:
    if boosted:
        return rng.choices(INTERACTION_ACTIONS, weights=[38, 22, 18, 12, 10], k=1)[0]
    return rng.choices(INTERACTION_ACTIONS, weights=[46, 8, 10, 6, 30], k=1)[0]


def _sample_dwell_seconds(rng: random.Random, action: str, boosted: bool) -> float:
    if action == "skip":
        return rng.uniform(1, 8)
    base = rng.uniform(18, 130)
    if action in {"like", "save", "share"}:
        base *= 1.35
    if boosted:
        base *= 1.2
    return min(base, 420)


def _make_referral_code(user_id: str) -> str:
    return f"DL-{user_id.upper()}"


def _next_user_id() -> str:
    max_id = 0
    for u in users:
        if u.id.startswith("u"):
            try:
                max_id = max(max_id, int(u.id[1:]))
            except ValueError:
                continue
    return f"u{max_id + 1}"


def _find_user_by_referral_code(code: str) -> Optional[User]:
    normalized = (code or "").strip().upper()
    for u in users:
        if u.referral_code.upper() == normalized:
            return u
    return None


def _referral_discount_percent(user_id: str) -> int:
    user = _get_user(user_id)
    return min(30, user.referral_count * 5)


def _normalize_focus_mode(value: str) -> Literal["strict", "balanced", "discovery"]:
    mode = (value or "").strip().lower()
    if mode in FOCUS_MODES:
        return mode  # type: ignore[return-value]
    return "balanced"


def _is_icp_role(role: str) -> bool:
    v = (role or "").lower()
    return any(token in v for token in ("ai", "ml", "data scientist", "machine learning", "research engineer"))


def _subject_bucket(subject: str) -> str:
    if subject in AI_CORE_SUBJECTS:
        return "core"
    if subject in AI_ADJACENT_SUBJECTS:
        return "adjacent"
    if subject in AI_FRONTIER_SUBJECTS:
        return "frontier"
    return "adjacent"


def _target_mix_for_user(user: User) -> Dict[str, float]:
    mode = _normalize_focus_mode(user.focus_mode)
    icp = _is_icp_role(user.role)
    if icp:
        if mode == "strict":
            return {"core": 0.85, "adjacent": 0.12, "frontier": 0.03}
        if mode == "discovery":
            return {"core": 0.55, "adjacent": 0.25, "frontier": 0.20}
        return {"core": 0.70, "adjacent": 0.20, "frontier": 0.10}
    if mode == "strict":
        return {"core": 0.55, "adjacent": 0.35, "frontier": 0.10}
    if mode == "discovery":
        return {"core": 0.35, "adjacent": 0.35, "frontier": 0.30}
    return {"core": 0.45, "adjacent": 0.35, "frontier": 0.20}


def _user_exists(user_id: str) -> bool:
    return any(user.id == user_id for user in users)


def _get_user(user_id: str) -> User:
    for user in users:
        if user.id == user_id:
            return user
    raise HTTPException(status_code=404, detail="User not found")


def _month_start(now: datetime) -> datetime:
    return datetime(year=now.year, month=now.month, day=1, tzinfo=timezone.utc)


def _posts_consumed_this_month(user_id: str, now: datetime) -> int:
    start = _month_start(now)
    consumed: Set[str] = set()
    for event in interactions:
        if event.user_id != user_id:
            continue
        if event.ts < start:
            continue
        if not event.article_id.startswith("a"):
            continue
        consumed.add(event.article_id)
    return len(consumed)


def _entitlement(user_id: str, now: Optional[datetime] = None) -> dict:
    ts = now or datetime.now(timezone.utc)
    user = _get_user(user_id)
    monthly_limit = POST_LIMITS_PER_MONTH[user.tier]
    used = _posts_consumed_this_month(user_id, ts)
    remaining = None if monthly_limit is None else max(monthly_limit - used, 0)
    can_consume = remaining is None or remaining > 0
    referral_discount_percent = _referral_discount_percent(user_id)

    return {
        "tier": user.tier,
        "monthly_limit": monthly_limit,
        "monthly_used": used,
        "monthly_remaining": remaining,
        "can_consume": can_consume,
        "ad_enabled": user.tier == "free",
        "billing_window_start": _month_start(ts).date().isoformat(),
        "referral_code": user.referral_code,
        "referral_count": user.referral_count,
        "renewal_discount_percent": referral_discount_percent,
    }


def _build_subject_affinity(user_id: str) -> Dict[str, float]:
    # Affinity is an exploit signal from historical behavior.
    # We apply time decay so recent interactions have more impact than old ones.
    affinity = {subject: 0.1 for subject in SUBJECTS}
    relevant = [x for x in interactions if x.user_id == user_id]

    if not relevant:
        return affinity

    action_weight = {
        "view": 1.0,
        "like": 2.8,
        "save": 2.4,
        "share": 3.0,
        "skip": -1.7,
    }

    article_subject = {a.id: a.subject for a in articles}
    now = datetime.now(timezone.utc)

    for item in relevant:
        age_days = max((now - item.ts).total_seconds() / 86400.0, 0.0)
        if age_days > INTERACTION_MAX_AGE_DAYS:
            continue
        subject = article_subject[item.article_id]
        time_signal = min(item.dwell_seconds / 45.0, 3.0)
        recency_decay = 0.5 ** (age_days / max(INTERACTION_HALF_LIFE_DAYS, 1e-6))
        affinity[subject] += action_weight[item.action] * (0.75 + time_signal) * recency_decay

    min_score = min(affinity.values())
    if min_score <= 0:
        shift = abs(min_score) + 0.2
        affinity = {k: v + shift for k, v in affinity.items()}

    total = sum(affinity.values())
    return {k: v / total for k, v in affinity.items()}


def _interaction_reward(action: str, dwell_seconds: float) -> float:
    action_base = {
        "view": 0.35,
        "like": 0.75,
        "save": 0.85,
        "share": 1.0,
        "skip": 0.05,
    }
    dwell_component = min(dwell_seconds / 120.0, 1.0)
    reward = 0.65 * action_base[action] + 0.35 * dwell_component
    if action == "skip":
        reward *= 0.35
    return max(0.0, min(1.2, reward))


def _build_bandit_scores(user_id: str) -> Tuple[Dict[str, float], Dict[str, int]]:
    # UCB-like exploration score with recency-weighted pulls/reward.
    # - weighted_pulls: controls uncertainty/novelty terms
    # - reward: controls mean payoff term
    # Raw pull counts are returned for diagnostics in the UI.
    subject_stats = {subject: {"pulls": 0, "weighted_pulls": 0.0, "reward": 0.0} for subject in SUBJECTS}
    relevant = [x for x in interactions if x.user_id == user_id]
    article_subject = {a.id: a.subject for a in articles}
    now = datetime.now(timezone.utc)

    for item in relevant:
        age_days = max((now - item.ts).total_seconds() / 86400.0, 0.0)
        if age_days > INTERACTION_MAX_AGE_DAYS:
            continue
        subject = article_subject.get(item.article_id)
        if subject is None:
            continue
        recency_decay = 0.5 ** (age_days / max(INTERACTION_HALF_LIFE_DAYS, 1e-6))
        subject_stats[subject]["pulls"] += 1
        subject_stats[subject]["weighted_pulls"] += recency_decay
        subject_stats[subject]["reward"] += _interaction_reward(item.action, item.dwell_seconds) * recency_decay

    total_pulls = sum(stats["weighted_pulls"] for stats in subject_stats.values())
    prior_mean = 0.42
    exploration_c = 1.3

    bandit_raw: Dict[str, float] = {}
    subject_pulls: Dict[str, int] = {}
    for subject, stats in subject_stats.items():
        pulls = int(stats["pulls"])
        weighted_pulls = float(stats["weighted_pulls"])
        reward_sum = float(stats["reward"])

        mean_reward = reward_sum / weighted_pulls if weighted_pulls > 0 else prior_mean
        uncertainty = math.sqrt(math.log(total_pulls + len(SUBJECTS) + 1) / (weighted_pulls + 1))
        novelty = 1.0 / math.sqrt(weighted_pulls + 1)

        bandit_raw[subject] = mean_reward + (exploration_c * uncertainty) + (0.2 * novelty)
        subject_pulls[subject] = pulls

    total = sum(bandit_raw.values())
    if total <= 0:
        uniform = 1.0 / len(SUBJECTS)
        return ({subject: uniform for subject in SUBJECTS}, subject_pulls)
    return ({subject: score / total for subject, score in bandit_raw.items()}, subject_pulls)


def _article_score(user_id: str, article: Article, affinity: Dict[str, float], bandit: Dict[str, float]) -> float:
    days_old = max((datetime.now(timezone.utc) - article.created_at).total_seconds() / 86400, 0)
    recency_boost = 1.0 / math.sqrt(days_old + 1)

    stable_rng = random.Random(f"{user_id}:{article.id}")
    editorial_quality = 0.8 + stable_rng.random() * 0.4
    diversity_jitter = stable_rng.random() * 0.35

    exploit_component = affinity[article.subject] * 6.2
    explore_component = bandit[article.subject] * 6.8
    return exploit_component + explore_component + recency_boost * 0.8 + editorial_quality + diversity_jitter


def _text_score(article: Article, query: str) -> float:
    q = query.strip().lower()
    if not q:
        return 0.0
    title = article.title.lower()
    summary = article.summary.lower()
    source = article.source.lower()

    score = 0.0
    if q in title:
        score += 2.5
    if q in summary:
        score += 1.2
    if q in source:
        score += 0.8
    return score


def _next_article_numeric_id() -> int:
    max_id = 0
    for article in articles:
        if article.id.startswith("a"):
            try:
                max_id = max(max_id, int(article.id[1:]))
            except ValueError:
                continue
    return max_id + 1


def _ingest_live_articles_for_search(query: str, subject_filter: str, max_new: int = 80) -> int:
    added = 0
    start_id = _next_article_numeric_id()
    existing_links = {a.url for a in articles if a.url}
    newly_added_articles: List[Article] = []

    if subject_filter and subject_filter in SUBJECTS:
        search_subjects = [subject_filter]
    else:
        search_subjects = SUBJECTS

    for subject in search_subjects:
        if added >= max_new:
            break

        query_parts = []
        base_topic = TOPIC_QUERIES.get(subject, "")
        if base_topic:
            query_parts.append(base_topic)
        if query:
            query_parts.append(query)
        if not query_parts:
            continue

        composed_query = quote_plus(" ".join(query_parts))
        rss_url = f"https://news.google.com/rss/search?q={composed_query}&hl=en-US&gl=US&ceid=US:en"

        try:
            with urlopen(rss_url, timeout=8) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
        except Exception:
            continue

        for item in root.findall("./channel/item"):
            if added >= max_new:
                break

            title = _clean_text((item.findtext("title") or "").strip())
            link = (item.findtext("link") or "").strip()
            summary = _clean_text(_strip_html(item.findtext("description") or ""))
            pub_date = _parse_pub_date(item.findtext("pubDate"))

            source_node = None
            for child in list(item):
                if child.tag.endswith("source"):
                    source_node = child
                    break
            source = _clean_text((source_node.text or "Unknown") if source_node is not None else "Unknown")

            if not title or not link or link in existing_links:
                continue

            existing_links.add(link)
            articles.append(
                Article(
                    id=f"a{start_id + added}",
                    title=title,
                    subject=subject,
                    summary=summary[:300] if summary else _clean_text(f"Recent article about {subject.lower()}."),
                    created_at=pub_date,
                    url=link,
                    source=source,
                )
            )
            newly_added_articles.append(articles[-1])
            added += 1

    _persist_articles_to_mongo(newly_added_articles)
    return added


def _mix_ranked_by_bucket(
    ranked: List[Tuple[float, Article]],
    user: User,
) -> List[Tuple[float, Article]]:
    # Deterministic scheduler that keeps feed composition near target bucket ratios
    # (core/adjacent/frontier) for the selected focus mode.
    if not ranked:
        return []

    target_mix = _target_mix_for_user(user)
    buckets: Dict[str, List[Tuple[float, Article]]] = {"core": [], "adjacent": [], "frontier": []}
    for item in ranked:
        buckets[_subject_bucket(item[1].subject)].append(item)

    counts = {"core": 0, "adjacent": 0, "frontier": 0}
    total_added = 0
    mixed: List[Tuple[float, Article]] = []

    while buckets["core"] or buckets["adjacent"] or buckets["frontier"]:
        deficits = {}
        for bucket_name in ("core", "adjacent", "frontier"):
            target = target_mix[bucket_name] * (total_added + 1)
            deficits[bucket_name] = target - counts[bucket_name]

        selected = None
        for bucket_name, _ in sorted(deficits.items(), key=lambda x: x[1], reverse=True):
            if buckets[bucket_name]:
                selected = bucket_name
                break

        if selected is None:
            break

        item = buckets[selected].pop(0)
        mixed.append(item)
        counts[selected] += 1
        total_added += 1

    return mixed


def _precompute_rank_bundle(user_id: str) -> dict:
    # Rank bundle is cached per-user and invalidated when user state version changes.
    # This keeps feed latency low while preserving deterministic pagination.
    version = user_state_version.get(user_id, 0)
    now_ts = time.time()
    cached = precomputed_rank_cache.get(user_id)
    if cached and cached.get("version") == version and cached.get("expires_at", 0) > now_ts:
        return cached

    affinity = _build_subject_affinity(user_id)
    bandit_scores, subject_pull_counts = _build_bandit_scores(user_id)
    consumed = seen_articles.get(user_id, set())
    now = datetime.now(timezone.utc)
    # Hard freshness guardrail for feed recommendations.
    freshness_cutoff = now - timedelta(days=max(MAX_FEED_ARTICLE_AGE_DAYS, 1))

    ranked = []
    for article in articles:
        if article.id in consumed:
            continue
        if article.created_at < freshness_cutoff:
            continue
        score = _article_score(user_id, article, affinity, bandit_scores)
        ranked.append((score, article))

    ranked.sort(key=lambda x: x[0], reverse=True)
    user = _get_user(user_id)
    mixed_ranked = _mix_ranked_by_bucket(ranked, user)
    bundle = {
        "version": version,
        "expires_at": now_ts + PRECOMPUTE_TTL_SECONDS,
        "affinity": affinity,
        "bandit_scores": bandit_scores,
        "subject_pull_counts": subject_pull_counts,
        "mixed_ranked": mixed_ranked,
        "target_mix": _target_mix_for_user(user),
        "focus_mode": _normalize_focus_mode(user.focus_mode),
    }
    precomputed_rank_cache[user_id] = bundle
    return bundle


def _inject_sponsored_cards(items: List[dict], entitlement: dict) -> List[dict]:
    if not entitlement.get("ad_enabled"):
        return items

    blended: List[dict] = []
    ad_idx = 0
    organic_count = 0
    for item in items:
        blended.append(item)
        if item.get("is_sponsored"):
            continue
        organic_count += 1
        if organic_count % 5 == 0 and ad_idx < len(SPONSORED_CARDS):
            ad = SPONSORED_CARDS[ad_idx]
            ad_idx += 1
            blended.append(
                {
                    "id": f"ad-{ad_idx}",
                    "title": ad["title"],
                    "subject": "Sponsored",
                    "summary": ad["summary"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "url": ad["url"],
                    "source": ad["source"],
                    "score": 0.0,
                    "is_sponsored": True,
                }
            )
    return blended


@app.on_event("startup")
def startup() -> None:
    global event_pipeline_mode, data_backend_mode
    data_backend_mode = "memory"
    if DATA_BACKEND == "mongo" and _mongo_init():
        data_backend_mode = "mongo"
        loaded = _load_state_from_mongo()
        if not loaded:
            _seed_data()
            _persist_snapshot_to_mongo()
            _log_event("mongo_seeded_from_fresh_data")
        else:
            _log_event("mongo_state_loaded")
    else:
        _seed_data()
        if DATA_BACKEND == "mongo":
            _log_event("mongo_unavailable_fallback_memory")
    if EVENT_PIPELINE_BACKEND == "kafka" and _kafka_available() and _start_kafka_pipeline():
        event_pipeline_mode = "kafka"
    else:
        event_pipeline_mode = "local"
        _start_event_processor()
        if EVENT_PIPELINE_BACKEND == "kafka" and not _kafka_available():
            _log_event("kafka_library_missing_fallback_local")
        elif EVENT_PIPELINE_BACKEND == "kafka":
            _log_event("kafka_start_failed_fallback_local")
    _log_event("event_pipeline_selected", mode=event_pipeline_mode)


@app.on_event("shutdown")
def shutdown() -> None:
    _stop_event_processor()
    _stop_kafka_pipeline()
    if mongo_client is not None:
        try:
            mongo_client.close()
        except Exception:
            pass


@app.get("/health")
def health() -> dict:
    started = time.perf_counter()
    ok = True
    try:
        return {
            "status": "ok",
            "article_count": len(articles),
            "event_queue_depth": event_queue.qsize() if event_pipeline_mode == "local" else -1,
            "event_pipeline_mode": event_pipeline_mode,
            "data_backend_mode": data_backend_mode,
            "mode": "v2-laptop-production-simulation",
        }
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/health", (time.perf_counter() - started) * 1000, ok)


@app.get("/api/users")
def get_users() -> list[dict]:
    started = time.perf_counter()
    ok = True
    now = datetime.now(timezone.utc)
    payload = []
    try:
        for user in users:
            ent = _entitlement(user.id, now)
            payload.append(
                {
                    "id": user.id,
                    "name": user.name,
                    "tier": user.tier,
                    "role": user.role,
                    "focus_mode": _normalize_focus_mode(user.focus_mode),
                    "referral_code": user.referral_code,
                    "referral_count": user.referral_count,
                    "monthly_limit": ent["monthly_limit"],
                    "monthly_used": ent["monthly_used"],
                    "monthly_remaining": ent["monthly_remaining"],
                    "renewal_discount_percent": ent["renewal_discount_percent"],
                    "icp_profile": _is_icp_role(user.role),
                }
            )
        return payload
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/users", (time.perf_counter() - started) * 1000, ok)


@app.post("/api/users/onboard")
def onboard_user(req: OnboardingRequest) -> dict:
    started = time.perf_counter()
    ok = True
    try:
        inviter: Optional[User] = None
        if req.referral_code:
            inviter = _find_user_by_referral_code(req.referral_code)
            if inviter is None:
                raise HTTPException(status_code=400, detail="Invalid referral code")

        user_id = _next_user_id()
        new_user = User(
            id=user_id,
            name=req.name.strip(),
            tier="free",
            role=req.role.strip(),
            focus_mode=_normalize_focus_mode(req.focus_mode),
            onboarding_completed=True,
            referral_code=_make_referral_code(user_id),
            referral_count=0,
            referred_by=inviter.id if inviter else None,
        )
        users.append(new_user)
        seen_articles[new_user.id] = set()
        user_state_version[new_user.id] = 0
        precomputed_rank_cache.pop(new_user.id, None)
        _invalidate_user_caches(new_user.id)

        ARRRR_METRICS["acquisition_signups"] += 1
        ARRRR_METRICS["activation_onboarded"] += 1
        if inviter is not None:
            inviter.referral_count += 1
            ARRRR_METRICS["referral_signups"] += 1
            ARRRR_METRICS["revenue_discount_events"] += 1

        _persist_snapshot_to_mongo()
        _log_event(
            "user_onboarded",
            user_id=new_user.id,
            role=new_user.role,
            interests=req.interests,
            referred_by=new_user.referred_by,
        )
        ent = _entitlement(new_user.id)
        return {
            "ok": True,
            "user": {
                "id": new_user.id,
                "name": new_user.name,
                "tier": new_user.tier,
                "role": new_user.role,
                "focus_mode": _normalize_focus_mode(new_user.focus_mode),
                "referral_code": new_user.referral_code,
                "referral_count": new_user.referral_count,
                "monthly_limit": ent["monthly_limit"],
                "monthly_used": ent["monthly_used"],
                "monthly_remaining": ent["monthly_remaining"],
                "renewal_discount_percent": ent["renewal_discount_percent"],
                "icp_profile": _is_icp_role(new_user.role),
            },
            "entitlement": ent,
            "message": "Welcome to DailyLens. Your AI onboarding is complete.",
        }
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/users/onboard", (time.perf_counter() - started) * 1000, ok)


@app.post("/api/users/focus")
def update_user_focus(req: UserFocusRequest) -> dict:
    started = time.perf_counter()
    ok = True
    try:
        if not _user_exists(req.user_id):
            raise HTTPException(status_code=404, detail="User not found")
        user = _get_user(req.user_id)
        user.focus_mode = _normalize_focus_mode(req.focus_mode)
        user_state_version[user.id] = user_state_version.get(user.id, 0) + 1
        _invalidate_user_caches(user.id)
        _persist_snapshot_to_mongo()
        _log_event("user_focus_mode_updated", user_id=user.id, focus_mode=user.focus_mode)
        return {"ok": True, "user_id": user.id, "focus_mode": user.focus_mode}
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/users/focus", (time.perf_counter() - started) * 1000, ok)


@app.post("/api/referrals/simulate-signup")
def simulate_referral_signup(req: ReferralSignupRequest) -> dict:
    started = time.perf_counter()
    ok = True
    try:
        if not _user_exists(req.inviter_user_id):
            raise HTTPException(status_code=404, detail="Inviter not found")
        inviter = _get_user(req.inviter_user_id)
        ARRRR_METRICS["referrals_sent"] += 1
        onboarding = OnboardingRequest(
            name=req.invitee_name,
            role=req.invitee_role,
            interests=req.interests,
            goal="Referred signup",
            referral_code=inviter.referral_code,
            focus_mode=inviter.focus_mode,
        )
        result = onboard_user(onboarding)
        return {
            "ok": True,
            "inviter_user_id": inviter.id,
            "inviter_referral_code": inviter.referral_code,
            "inviter_referral_count": inviter.referral_count,
            "inviter_renewal_discount_percent": _referral_discount_percent(inviter.id),
            "new_user": result["user"],
        }
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/referrals/simulate-signup", (time.perf_counter() - started) * 1000, ok)


@app.post("/api/refresh")
def refresh_feed_data() -> dict:
    started = time.perf_counter()
    ok = True
    try:
        _seed_data()
        _persist_snapshot_to_mongo()
        _log_event("content_refreshed", article_count=len(articles), interaction_count=len(interactions))
        return {
            "ok": True,
            "article_count": len(articles),
            "user_count": len(users),
            "interaction_count": len(interactions),
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/refresh", (time.perf_counter() - started) * 1000, ok)


@app.post("/api/feed")
def get_feed(req: FeedRequest) -> dict:
    started = time.perf_counter()
    ok = True
    cache_hit = False
    try:
        if not _user_exists(req.user_id):
            raise HTTPException(status_code=404, detail="User not found")
        _enforce_rate_limit(req.user_id, "/api/feed")
        ent = _entitlement(req.user_id)

        if not ent["can_consume"]:
            user = _get_user(req.user_id)
            return {
                "items": [],
                "next_offset": req.offset,
                "has_more": False,
                "subject_affinity": {subject: 1.0 / len(SUBJECTS) for subject in SUBJECTS},
                "exploration_subject_scores": {subject: 1.0 / len(SUBJECTS) for subject in SUBJECTS},
                "bandit_subject_scores": {subject: 1.0 / len(SUBJECTS) for subject in SUBJECTS},
                "subject_pull_counts": {subject: 0 for subject in SUBJECTS},
                "feed_focus_mode": _normalize_focus_mode(user.focus_mode),
                "topic_buckets": {subject: _subject_bucket(subject) for subject in SUBJECTS},
                "target_mix": _target_mix_for_user(user),
                "entitlement": ent,
                "message": "Monthly post limit reached for current tier.",
            }

        # Feed pages are cached by (user, offset, limit, user-state-version).
        # Version bump on new interactions/focus changes guarantees consistency.
        version = user_state_version.get(req.user_id, 0)
        key = _cache_key_feed(req.user_id, req.offset, req.limit, version)
        cached = feed_page_cache.get(key)
        global feed_cache_hits, feed_cache_misses
        if cached and cached[0] > time.time():
            cache_hit = True
            feed_cache_hits += 1
            return cached[1]
        feed_cache_misses += 1

        bundle = _precompute_rank_bundle(req.user_id)
        mixed_ranked = bundle["mixed_ranked"]
        affinity = bundle["affinity"]
        bandit_scores = bundle["bandit_scores"]
        subject_pull_counts = bundle["subject_pull_counts"]
        feed_focus_mode = bundle["focus_mode"]
        target_mix = bundle["target_mix"]

        if not mixed_ranked:
            return {
                "items": [],
                "next_offset": req.offset,
                "has_more": False,
                "subject_affinity": affinity,
                "exploration_subject_scores": bandit_scores,
                "bandit_subject_scores": bandit_scores,
                "subject_pull_counts": subject_pull_counts,
                "feed_focus_mode": feed_focus_mode,
                "topic_buckets": {subject: _subject_bucket(subject) for subject in SUBJECTS},
                "target_mix": target_mix,
                "entitlement": ent,
                "message": f"No fresh recommendations in the last {MAX_FEED_ARTICLE_AGE_DAYS} days. Refresh the news pool.",
            }

        # Pagination is applied after ranking/mixing so infinite scroll is stable.
        window = mixed_ranked[req.offset : req.offset + req.limit]
        items = [
            {
                "id": item.id,
                "title": item.title,
                "subject": item.subject,
                "summary": item.summary,
                "created_at": item.created_at.isoformat(),
                "url": item.url,
                "source": item.source,
                "score": round(score, 3),
                "is_sponsored": False,
            }
            for score, item in window
        ]
        items = _inject_sponsored_cards(items, ent)

        next_offset = req.offset + len(window)
        has_more = next_offset < len(mixed_ranked)
        response = {
            "items": items,
            "next_offset": next_offset,
            "has_more": has_more,
            "subject_affinity": affinity,
            "exploration_subject_scores": bandit_scores,
            "bandit_subject_scores": bandit_scores,
            "subject_pull_counts": subject_pull_counts,
            "feed_focus_mode": feed_focus_mode,
            "topic_buckets": {subject: _subject_bucket(subject) for subject in SUBJECTS},
            "target_mix": target_mix,
            "entitlement": ent,
        }
        feed_page_cache[key] = (time.time() + FEED_CACHE_TTL_SECONDS, response)
        return response
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/feed", (time.perf_counter() - started) * 1000, ok, cache_hit=cache_hit)


@app.post("/api/explore")
def explore_catalog(req: ExploreRequest) -> dict:
    started = time.perf_counter()
    ok = True
    try:
        if not _user_exists(req.user_id):
            raise HTTPException(status_code=404, detail="User not found")
        _enforce_rate_limit(req.user_id, "/api/explore")
        ent = _entitlement(req.user_id)

        if not ent["can_consume"] and not req.include_seen:
            return {
                "items": [],
                "next_offset": req.offset,
                "has_more": False,
                "total": 0,
                "subjects": SUBJECTS,
                "entitlement": ent,
                "message": "Monthly post limit reached for current tier.",
            }

        query = (req.query or "").strip()
        subject_filter = (req.subject or "").strip()
        consumed = seen_articles.get(req.user_id, set())

        if query or subject_filter:
            _ingest_live_articles_for_search(query=query, subject_filter=subject_filter, max_new=80)

        candidates: List[Tuple[float, Article]] = []
        now = datetime.now(timezone.utc)

        for article in articles:
            if not req.include_seen and article.id in consumed:
                continue
            if subject_filter and article.subject != subject_filter:
                continue

            tscore = _text_score(article, query) if query else 0.0
            if query and tscore <= 0:
                continue

            days_old = max((now - article.created_at).total_seconds() / 86400, 0.0)
            recency = 1.0 / math.sqrt(days_old + 1)
            combined = tscore * 2.0 + recency
            candidates.append((combined, article))

        candidates.sort(key=lambda x: x[0], reverse=True)
        window = candidates[req.offset : req.offset + req.limit]

        items = [
            {
                "id": item.id,
                "title": item.title,
                "subject": item.subject,
                "summary": item.summary,
                "created_at": item.created_at.isoformat(),
                "url": item.url,
                "source": item.source,
                "score": round(score, 3),
                "is_sponsored": False,
            }
            for score, item in window
        ]
        items = _inject_sponsored_cards(items, ent)

        next_offset = req.offset + len(window)
        has_more = next_offset < len(candidates)
        return {
            "items": items,
            "next_offset": next_offset,
            "has_more": has_more,
            "total": len(candidates),
            "subjects": SUBJECTS,
            "entitlement": ent,
        }
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/explore", (time.perf_counter() - started) * 1000, ok)


@app.post("/api/interactions")
def add_interaction(req: InteractionRequest) -> dict:
    started = time.perf_counter()
    ok = True
    try:
        if not _user_exists(req.user_id):
            raise HTTPException(status_code=404, detail="User not found")
        if req.article_id.startswith("ad-"):
            return {"ok": True, "ignored": "sponsored"}
        if not any(article.id == req.article_id for article in articles):
            raise HTTPException(status_code=404, detail="Article not found")

        already_seen = req.article_id in seen_articles.get(req.user_id, set())
        ent = _entitlement(req.user_id)
        if not already_seen and not ent["can_consume"]:
            raise HTTPException(
                status_code=402,
                detail={
                    "message": "Monthly post limit reached. Upgrade tier to continue.",
                    "tier": ent["tier"],
                    "monthly_limit": ent["monthly_limit"],
                    "monthly_used": ent["monthly_used"],
                    "monthly_remaining": ent["monthly_remaining"],
                },
            )

        event = Interaction(
            user_id=req.user_id,
            article_id=req.article_id,
            action=req.action,
            dwell_seconds=req.dwell_seconds,
            ts=datetime.now(timezone.utc),
        )
        interactions.append(event)
        seen_articles[req.user_id].add(req.article_id)
        _persist_interaction_to_mongo(event)

        user_state_version[req.user_id] = user_state_version.get(req.user_id, 0) + 1
        _invalidate_user_caches(req.user_id)

        _publish_stream_event(
            {
                "user_id": req.user_id,
                "article_id": req.article_id,
                "action": req.action,
                "dwell_seconds": req.dwell_seconds,
            }
        )

        _log_event("interaction_added", user_id=req.user_id, action=req.action, article_id=req.article_id)
        return {"ok": True, "entitlement": _entitlement(req.user_id)}
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/interactions", (time.perf_counter() - started) * 1000, ok)


@app.get("/api/monitoring/dashboard")
def monitoring_dashboard() -> dict:
    started = time.perf_counter()
    ok = True
    try:
        metrics_payload = {}
        for endpoint, value in endpoint_metrics.items():
            count = value.get("count", 0)
            p95_buffer = sorted(value.get("latency_p95_buffer", []))
            p95_idx = int(0.95 * (len(p95_buffer) - 1)) if p95_buffer else 0
            p95 = p95_buffer[p95_idx] if p95_buffer else 0.0
            metrics_payload[endpoint] = {
                "count": count,
                "errors": value.get("errors", 0),
                "avg_latency_ms": round(value.get("latency_total_ms", 0.0) / max(count, 1), 2),
                "p95_latency_ms": round(p95, 2),
                "cache_hit_count": value.get("cache_hit_count", 0),
            }

        tier_counts = {"free": 0, "silver": 0, "gold": 0}
        for user in users:
            tier_counts[user.tier] += 1

        return {
            "runtime_mode": f"v2-laptop-production-simulation:{event_pipeline_mode}",
            "data_layer_plan": {
                "nosql_primary": "mongodb" if data_backend_mode == "mongo" else "simulated(in-memory)",
                "nosql_distributed_note": "MongoDB supports sharding/replica sets for production distribution",
                "redis": "simulated(in-memory)",
                "analytics_warehouse": "simulated(endpoint metrics + logs)",
            },
            "event_pipeline": {
                "queue_backend": "kafka(redpanda-compatible)" if event_pipeline_mode == "kafka" else "local(queue.Queue)",
                "queue_depth": event_queue.qsize() if event_pipeline_mode == "local" else -1,
                "events_processed": events_processed,
                "events_failed": events_failed,
                "events_dropped": event_queue_dropped,
                "events_published": events_published,
                "events_publish_failed": events_publish_failed,
                "kafka_bootstrap_servers": KAFKA_BOOTSTRAP_SERVERS if event_pipeline_mode == "kafka" else "",
                "kafka_topic": KAFKA_TOPIC if event_pipeline_mode == "kafka" else "",
            },
            "feed_serving": {
                "feed_cache_entries": len(feed_page_cache),
                "feed_cache_ttl_seconds": FEED_CACHE_TTL_SECONDS,
                "feed_cache_hits": feed_cache_hits,
                "feed_cache_misses": feed_cache_misses,
                "precomputed_user_bundles": len(precomputed_rank_cache),
            },
            "rate_limits": {
                "window_seconds": RATE_LIMIT_WINDOW_SECONDS,
                "limits_per_window": RATE_LIMITS_PER_WINDOW,
            },
            "traffic_metrics": metrics_payload,
            "data_backend_mode": data_backend_mode,
            "mongo_write_failures": mongo_write_failures,
            "arrrr_metrics": ARRRR_METRICS,
            "user_mix": tier_counts,
            "recent_logs": list(recent_logs)[:80],
        }
    except Exception:
        ok = False
        raise
    finally:
        _record_endpoint_metric("/api/monitoring/dashboard", (time.perf_counter() - started) * 1000, ok)
