"use client";

import { useMemo } from "react";
import type { FeedItem, InteractionAction } from "@/lib/types";

type Props = {
  item: FeedItem;
  onAction: (articleId: string, action: InteractionAction, dwellSeconds: number) => Promise<void>;
  onLinkClick: (articleId: string, dwellSeconds: number) => Promise<void>;
  mountedAt: number;
};

const buttonStyle: Record<Exclude<InteractionAction, "view">, string> = {
  like: "btn-like",
  save: "btn-save",
  share: "btn-share",
  skip: "btn-skip",
};

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(iso));
}

export function ArticleCard({ item, onAction, onLinkClick, mountedAt }: Props) {
  const age = useMemo(() => formatDate(item.created_at), [item.created_at]);
  const sponsored = Boolean(item.is_sponsored);

  const getDwellSeconds = () => Math.max(1, (performance.now() - mountedAt) / 1000);

  return (
    <article className={`article-card ${sponsored ? "sponsored-card" : ""}`}>
      <div className="article-meta">
        <span className="article-subject">{sponsored ? "Sponsored" : item.subject}</span>
        <span>
          {age} • {item.source || "Unknown"}
        </span>
      </div>

      <h3 className="article-title">
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={async () => {
              if (!sponsored) {
                await onLinkClick(item.id, getDwellSeconds());
              }
            }}
          >
            {item.title}
          </a>
        ) : (
          item.title
        )}
      </h3>

      <p className="article-summary">{item.summary}</p>

      {sponsored ? (
        <div className="article-actions">
          <a className="action-btn btn-share sponsor-cta" href={item.url} target="_blank" rel="noopener noreferrer">
            Visit Sponsor
          </a>
        </div>
      ) : (
        <div className="article-actions">
          {(["like", "save", "share", "skip"] as const).map((action) => (
            <button
              key={action}
              className={`action-btn ${buttonStyle[action]}`}
              onClick={async () => onAction(item.id, action, getDwellSeconds())}
            >
              {action}
            </button>
          ))}
        </div>
      )}
    </article>
  );
}
