# Marine Agent — Development Plan & Session Handoff

> **Where to store memory:** Keep project state here in `plan.md` (version-controlled, survives new sessions, agents read it on clone). README `## Roadmap` stays a short public checklist — sync both when shipping. Optional: Grok/Cursor user memory for personal prefs only, not task state.

**Production:** [marine-agent.vercel.app](https://marine-agent.vercel.app) · API [marine-agent.onrender.com](https://marine-agent.onrender.com)  
**Last plan update:** 2026-07-01 · **Latest commit:** see `git log -1`

---

## Shipped (dashboard + API)

- [x] PWA + Render API, 21 Gulf beaches, map sync, official flag colors
- [x] Unified outlook — water now vs plan (time-of-day: today / tonight / tomorrow)
- [x] Activity status (paddling, swimming, beach) with per-activity reasons
- [x] Nearby ranking `/api/rank` within 50 mi (today + tomorrow)
- [x] `outlook_tomorrow` + Open-Meteo daytime surf estimate for tomorrow rank
- [x] Saved home beach (`localStorage` key: `marineagent-home-beach`)
- [x] NWS storm badges, hourly “chance of rain”, readable hour labels
- [x] Radar proximity (Phase C) — cyan pulse; separate from official flag
- [x] MCP tools: `get_beach_conditions`, `rank_beaches` (incl. `when=tomorrow`)
- [x] Tide fixes (Sarasota/Manatee stations), cold-start / rank tiers
- [x] Surf period plain-language note; surf paired with shark/water above forecast

---

## Next up (priority order)

### 1. In-app chat — highest product gap
**Goal:** “Best paddle near Venice today?” inside the PWA.

| Step | Effort | Notes |
|------|--------|-------|
| `/api/chat` proxy on Render | ~0.5 day | Keep `GEMINI_API_KEY` server-side |
| React chat drawer / FAB | ~1 day | Calls LLM with function tools → existing API |
| Wire tools: `get_beach_conditions`, `rank_beaches` | ~0.5 day | Already exist on MCP; mirror for HTTP |

**Skip for production:** Streamlit (dev-only). **Optional fast path:** Telegram bot for share-with-family.

### 2. Tomorrow polish (v1.1)
- [ ] Tomorrow **wind** from NWS period text or Open-Meteo (rank still uses current wind obs)
- [ ] Hero **Detailed Forecast** card: show tomorrow period when planning toggle = Tomorrow
- [ ] Dedupe Water & Algae card JSX in `App.tsx` (minor refactor)

### 3. Atlantic coast expansion
- [ ] Add East Coast beaches to `BEACH_CONFIG` (tide stations, NWS points, Mote fallbacks)
- [ ] `coast` filter on `/api/rank` (param exists, not fully used)

### 4. Ops / quality backlog
- [ ] README: align copy (“Today’s outlook” not “Today’s Verdict” everywhere)
- [ ] FWC red tide SSL (`verify=False` workaround)
- [ ] `get_beach_key()` fuzzy-match edge cases (e.g. substring “key”)
- [ ] Hardcoded skywatch events → ephemeris or remove
- [ ] Request-level TTLCache on hot fetchers (`_get_nws_obs`, etc.)

### 5. Later
- [ ] Native iOS (Capacitor + TestFlight) if PWA isn’t enough
- [ ] Push notifications for red flag / NWS warnings
- [ ] iMessage — not feasible without Apple Business Chat

---

### 6. User Reports — "Beach Pulse" (Community Beach Conditions)

**Goal:** Beachgoers submit one-tap hazard/condition reports from the beach. The killer-feature bet: fuse NOAA/NWS official data with real-time human eyes-on-the-sand into one trustworthy signal — without becoming Mote's broken, high-friction report flow, and without turning into a second data feed the user has to mentally reconcile. Primary audience: parents/families (repeat, safety-motivated, kids in the water) and retirees/casual goers (infrequent, low patience for friction).

**Core design principle:** the existing go/no-go verdict is never rewritten by reports. Beach Pulse is a separate, adjacent signal — this is the fix for decision-paralysis: one clean verdict, always answerable in 3 seconds, plus an honest "here's what people are seeing" layer next to it.

#### Report categories
| Category | Icon | Severity tier |
|----------|------|----------------|
| Water clarity | 👁️ | Low — publishes on 1 verified report |
| Crowd level | 👥 | Low |
| Dog-friendly confirmation | 🐕 | Low |
| Parking (full/available) | 🅿️ | Low |
| Debris / Trash | 🗑️ | Low |
| Algae / Seaweed | 🌿 | Low — complements FWC HAB data |
| Dead fish | 🐟 | Moderate — often correlates with red tide |
| Rough surf / Waves | 🌊 | Moderate |
| Jellyfish / Man-o-war | 🪼 | Moderate — most common Gulf hazard |
| Riptide / Strong current | 🌀 | **High — panic-capable** |
| Shark sighting | 🦈 | **High — panic-capable** |
| Red tide / toxic water | ☠️ | **High — panic-capable** |

#### Trust model — Sign in with Apple/Google, not email magic-link
- One-tap OAuth (Face ID / Google one-tap) — no typing, no waiting on an inbox. This is what actually fixes Mote's friction (the wait, not the identity), and Sign in with Apple is groundwork the iOS App Store goal needs anyway (Apple guideline 4.8).
- A real OAuth identity (vs. disposable email) is the anti-abuse layer: much harder to mass-fake than magic-link emails, which matters most for **High** tier categories that can trigger real panic if spoofed (e.g. a brigaded "shark" report at a packed family beach).
- Rate limit + spike detection per verified account: a burst of identical severe reports from new accounts in a short window auto-holds for review instead of publishing.
- **Visibility vs. escalation are separate — a solo report is never fully hidden.** A single report, any severity, any beach, publishes immediately in a neutral "unconfirmed" state. Corroboration only gates *escalation* to a confirmed/alarming badge state, not whether it's visible at all. Full suppression (`held_for_review`) is reserved for spike/anomaly detection — a burst of matching reports from new accounts in a short window — which is the actual abuse signature, not "only one person happened to be there." This is what makes it safe to enable reports everywhere from day 1 (see below): there's no density threshold a beach has to clear before its reports "work."
  - **Low** — publishes immediately, no escalation concept needed.
  - **Moderate** — publishes immediately as "unconfirmed"; escalates to confirmed tone on a 2nd corroborating report or a Local Guide report (see below).
  - **High** — publishes immediately as "unconfirmed, awaiting confirmation" (explicit copy, so it never reads as broken); escalates the same way. Spike detection, not corroboration, is what can hold one for review.
- Digest opt-in (not a gate): after saving a home/favorite beach, offer "daily conditions + reports heads-up for [Beach]" via the email already available from OAuth. Solves retiree/infrequent-user re-engagement without needing push notifications or the native app first.

#### Local Guide status (earned, not granted) + cold start
- **Enable `reports_enabled: true` for all beaches in `BEACH_CONFIG` from day 1** — no engineering reason to restrict it once visibility no longer depends on local density (see above). The founder's actual visits (`manasota-key`, `englewood`, `venice`, occasionally `siesta`/`lido`) will organically be where the first Local Guides and richest data show up; other beaches just stay quiet (absent Beach Pulse chip) until someone reports there — same as the app looks today, not a worse look.
- **Local Guide status is earned, not a manual allowlist**: a reporter auto-promotes to Local Guide *for a given beach* after N (e.g. 3) of their reports there get corroborated within a recent window. A Local Guide's report counts as pre-corroborated — it escalates immediately, same effect the old "Trusted Local Reporter" override was reaching for, but data-driven and self-serve instead of an admin table the founder has to maintain.
- Local Guide is shown as a small badge (🏅) next to that user's own reports — a visible-quality signal for other users, and the seed of a points system without yet building a scored leaderboard.
- **Empty state is the existing UI, unchanged**: the Beach Pulse chip is *absent* (not "0 reports") when nothing exists for a beach.

#### Data model (Supabase / Postgres)
```sql
-- reports table
id             uuid primary key default gen_random_uuid()
beach_id       text not null          -- matches BEACH_CONFIG key
report_type    text not null          -- jellyfish | algae | riptide | surf | dead_fish | shark | debris | clarity | crowd | dog | parking | red_tide
severity_tier  text not null          -- low | moderate | high (fixed per report_type, not user-selectable)
notes          text                   -- optional 140-char free text
reporter_id    text not null          -- hashed OAuth subject id (Apple/Google), never plaintext email
status         text default 'published' -- published (always, on submit) | escalated | held_for_review (spike-detected only)
corroborated_by text[]                -- reporter_ids of corroborating reports, if any
created_at     timestamptz default now()
beach_lat      float                  -- optional, from GPS if user permits
beach_lng      float

-- reporter_beach_standing (derives Local Guide status)
reporter_id       text
beach_id          text
corroborated_count int default 0     -- increments when one of this reporter's reports gets corroborated
is_local_guide    bool default false  -- auto-set true at corroborated_count >= 3
points            int default 0       -- quality-weighted: corroborated reports only, not raw submit count

-- daily_report_aggregates (materialized or scheduled view)
beach_id     text
report_date  date
report_type  text
count        int
-- enables YoY / MoM / WoW / daily trend charts
```

#### New API endpoints
```
POST /api/reports                        -- submit report; tier logic decides published/pending/held
GET  /api/reports/{beach_id}             -- today's published reports for a beach
GET  /api/reports/{beach_id}/history     -- aggregates: ?grain=daily|weekly|monthly&lookback=30d
POST /api/auth/callback                  -- Apple/Google OAuth callback → session + reporter_id
```

#### UI integration
1. **FAB on beach detail** — "Report conditions" → icon grid, one tap, no form; every report posts immediately, High-tier categories just carry "unconfirmed, awaiting confirmation" copy until escalated
2. **Beach Pulse badge** — adjacent to (never inside) the main verdict; absent / neutral-unconfirmed / escalated-confirmed states per the trust model above
3. **Community reports section** in beach detail — chronological list of today's published reports, Local Guide reports marked with 🏅; link to historical trend chart

#### Influence on activity status
- Beach Pulse **never rewrites** the primary Swimming/Paddling/Beach verdict — it sits beside it.
- Confirmed Moderate/High reports may add a short qualifier line under the verdict (e.g. "🪼 3 reports, last 40 min") — same verdict, additional context, not a second verdict to weigh.

#### Historical / trend vision
- Daily report counts per beach per category stored permanently
- Future: sparkline on beach card ("jellyfish reports this week vs. last year same week")
- Future: heatmap calendar view per beach (like GitHub contributions)
- Feeds into seasonal pattern detection (e.g. "jellyfish season typically peaks in August at Venice")

#### Future: condition-based rankings (replaces activity filter)
Activity filter (paddling / swimming / beach) works today but is derived entirely from official data. Once community reports accumulate, replace or extend with:
- **Calmest beaches** — lowest surf + no riptide reports + no hazard flags
- **Waviest beaches** — highest surf score (for surfers/bodyboarders)
- **Most dangerous** — high riptide + jellyfish + red flag combo
- **Cleanest water** — low HAB + no dead fish/debris reports + clear water reports
This is a natural evolution: "best for paddling" ≈ "calmest" today; community data makes it richer.

#### Future: Local Guide points & leaderboard
Deferred past MVP — the `points`/`is_local_guide` fields above are enough to earn and display Local Guide status now. A full scored leaderboard is a real added surface (anti-gaming for points themselves, ranking UI, badge tiers) and premature with a small report base — a leaderboard of 3 names in week one undercuts the "not bloated" goal. Revisit once report volume across the 21 beaches justifies it.

#### Build steps
| Step | Effort | Dependency |
|------|--------|------------|
| Supabase project + `reports` table + RLS | 0.5 day | New: Supabase account |
| Sign in with Apple/Google (Supabase Auth) | 1 day | Supabase; Apple Developer account for App Store anyway |
| `POST /api/reports` + severity-tier publish logic + rate/spike limits | 1 day | Supabase |
| `GET /api/reports/{beach_id}` + integrate into `/api/conditions` response | 0.5 day | above |
| Report FAB + icon-grid bottom sheet UI | 1 day | API ready |
| Beach Pulse badge (adjacent to verdict, 3 states) | 0.5 day | API ready |
| `reports_enabled: true` default across all `BEACH_CONFIG` entries | trivial | `BEACH_CONFIG` |
| `reporter_beach_standing` table + Local Guide auto-promotion job | 0.5 day | reports table |
| Daily aggregate job + history endpoint | 0.5 day | reports table |
| Historical trend chart (sparkline) | 1 day | history endpoint |
| **Total estimate** | **~7 days** | |

#### Open questions / decisions deferred
- Local Guide promotion threshold: 3 corroborated reports at a beach is a starting guess, tune once real data exists
- Moderation: explicit flag/hide button, or rely entirely on spike-detection auto-hold for now?
- Digest cadence/channel: daily email to start; SMS is a later add once volume justifies the cost

---

## Architecture quick reference

| Piece | Location |
|-------|----------|
| Outlook / tomorrow logic | `marine_server.py` — `_analyze_*_situation`, `_build_outlook`, `rank_beaches_data` |
| Frontend planning toggle | `web/src/App.tsx` — `planningHorizon`, `planOutlook`, rank panel |
| Home beach | `web/src/App.tsx` — `HOME_BEACH_KEY` |
| Deploy | Vercel (`web/`) + Render (`marine_server.py`, `render.yaml`) |
| Database (planned) | Supabase — `reports` table, Sign in with Apple/Google auth, daily aggregates |

**Key API**
```
GET /api/conditions/{beach_id}
GET /api/rank?activity=paddling&when=today|tomorrow&beach_id=venice&radius_miles=50
GET /api/beaches_with_flags
```

---

## Original chat roadmap (still valid)

### Phase 1: MCP conversational access ✅
Use Cursor / Gemini CLI / Grok with MCP at `/mcp/sse` — works today, no new UI.

### Phase 2: Streamlit — **deferred** (demo only)

### Phase 3: Production chat
1. In-app chat sidebar (recommended)
2. Telegram bot (optional)
3. Grok Remote MCP (endpoint live)

---

## AI collaboration notes

- Prefer **git** on `main` for truth; `plan.md` updated each major session.
- GitHub connector for repo ops when available.
- User rule: run builds / verify locally before pushing major UI changes.

---

*Update this file at end of session when priorities or shipped items change.*