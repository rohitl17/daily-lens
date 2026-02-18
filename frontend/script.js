const API_BASE = "http://localhost:8000";

const state = {
  currentUserId: null,
  offset: 0,
  limit: 10,
  loading: false,
  hasMore: false,
};

const userSelect = document.getElementById("userSelect");
const loginBtn = document.getElementById("loginBtn");
const feedEl = document.getElementById("feed");
const statusEl = document.getElementById("status");
const affinityListEl = document.getElementById("affinityList");
const sentinel = document.getElementById("sentinel");
const template = document.getElementById("articleTemplate");

function setStatus(msg) {
  statusEl.textContent = msg;
}

async function fetchJson(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

function formatDate(iso) {
  const dt = new Date(iso);
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function sortAffinity(affinity) {
  return Object.entries(affinity).sort((a, b) => b[1] - a[1]);
}

function renderAffinity(affinity) {
  affinityListEl.innerHTML = "";
  const sorted = sortAffinity(affinity);

  for (const [subject, score] of sorted) {
    const li = document.createElement("li");
    const pct = Math.round(score * 100);
    li.innerHTML = `
      <span>${subject}</span>
      <div class="bar-wrap">
        <div class="bar" style="width:${pct}%;"></div>
      </div>
      <strong>${pct}%</strong>
    `;
    affinityListEl.appendChild(li);
  }
}

async function sendInteraction(articleId, action, dwellSeconds) {
  if (!state.currentUserId) return;

  await fetchJson("/api/interactions", {
    method: "POST",
    body: JSON.stringify({
      user_id: state.currentUserId,
      article_id: articleId,
      action,
      dwell_seconds: dwellSeconds,
    }),
  });
}

function removeCard(card) {
  card.classList.add("fade-out");
  setTimeout(() => card.remove(), 180);
}

function mountCard(item) {
  const frag = template.content.cloneNode(true);
  const card = frag.querySelector(".card");
  const title = frag.querySelector(".title");
  const subject = frag.querySelector(".subject");
  const date = frag.querySelector(".date");
  const summary = frag.querySelector(".summary");
  const buttons = frag.querySelectorAll("button[data-action]");
  const inViewStartedAt = performance.now();

  card.dataset.articleId = item.id;
  if (item.url) {
    const link = document.createElement("a");
    link.href = item.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = item.title;
    link.addEventListener("click", () => {
      if (card.dataset.viewLogged === "1") return;
      card.dataset.viewLogged = "1";

      const dwellSeconds = Math.max(1, (performance.now() - inViewStartedAt) / 1000);
      sendInteraction(item.id, "view", dwellSeconds).catch((err) => {
        setStatus(`Failed to log view: ${err.message}`);
      });
      removeCard(card);
      setStatus(`Tracked: view on article ${item.id}. Loading next items...`);
      void loadNextPageIfNeeded();
      void refreshAffinity();
    });
    title.replaceChildren(link);
  } else {
    title.textContent = item.title;
  }
  subject.textContent = item.subject;
  date.textContent = `${formatDate(item.created_at)} · ${item.source || "Unknown"}`;
  summary.textContent = item.summary;

  for (const btn of buttons) {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      const dwellSeconds = Math.max(1, (performance.now() - inViewStartedAt) / 1000);

      btn.disabled = true;
      try {
        await sendInteraction(item.id, action, dwellSeconds);
        removeCard(card);
        setStatus(`Tracked: ${action} on article ${item.id}. Loading next items...`);
        await loadNextPageIfNeeded();
        await refreshAffinity();
      } catch (err) {
        btn.disabled = false;
        setStatus(`Failed to log interaction: ${err.message}`);
      }
    });
  }

  feedEl.appendChild(frag);
}

async function refreshAffinity() {
  if (!state.currentUserId) return;
  const data = await fetchJson("/api/feed", {
    method: "POST",
    body: JSON.stringify({ user_id: state.currentUserId, offset: 0, limit: 1 }),
  });
  renderAffinity(data.subject_affinity);
}

async function loadUsers() {
  const users = await fetchJson("/api/users");
  userSelect.innerHTML = "";

  for (const user of users) {
    const opt = document.createElement("option");
    opt.value = user.id;
    opt.textContent = `${user.name} (${user.id})`;
    userSelect.appendChild(opt);
  }
}

async function loadFeedPage() {
  if (!state.currentUserId || state.loading || !state.hasMore) {
    return;
  }

  state.loading = true;
  setStatus("Loading more ranked articles...");

  try {
    const payload = {
      user_id: state.currentUserId,
      offset: state.offset,
      limit: state.limit,
    };

    const data = await fetchJson("/api/feed", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    for (const item of data.items) {
      mountCard(item);
    }

    state.offset = data.next_offset;
    state.hasMore = data.has_more;
    renderAffinity(data.subject_affinity);

    if (!data.items.length && !state.hasMore) {
      setStatus("No more articles for this user right now.");
    } else if (!state.hasMore) {
      setStatus("Reached end of feed.");
    } else {
      setStatus("Scroll for more.");
    }
  } catch (err) {
    setStatus(`Error loading feed: ${err.message}`);
  } finally {
    state.loading = false;
  }
}

async function loadNextPageIfNeeded() {
  const cards = feedEl.querySelectorAll(".card").length;
  if (cards < 6 && state.hasMore) {
    await loadFeedPage();
  }
}

async function startSession() {
  state.currentUserId = userSelect.value;
  state.offset = 0;
  state.hasMore = true;
  feedEl.innerHTML = "";

  await loadFeedPage();
  await loadNextPageIfNeeded();
}

const observer = new IntersectionObserver(
  async (entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        await loadFeedPage();
      }
    }
  },
  { rootMargin: "900px 0px" }
);

loginBtn.addEventListener("click", async () => {
  await startSession();
});

observer.observe(sentinel);

(async function init() {
  try {
    setStatus("Connecting to backend...");
    await fetchJson("/health");
    await loadUsers();
    setStatus("Ready. Choose a user and load feed.");
  } catch (err) {
    setStatus(`Backend unavailable: ${err.message}`);
  }
})();
