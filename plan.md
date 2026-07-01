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
- **Severity-tiered publishing**, not one-size-fits-all:
  - **Low** — publishes immediately on 1 verified report.
  - **Moderate** — publishes on 1 report, shown as "unconfirmed" (neutral tone) until a 2nd corroborating report arrives, then escalates.
  - **High** — requires 2+ corroborating reports OR a Trusted Local Reporter (see cold start below) before ever becoming publicly visible. Never auto-publish a solo high-severity report from an unknown account.
- Digest opt-in (not a gate): after saving a home/favorite beach, offer "daily conditions + reports heads-up for [Beach]" via the email already available from OAuth. Solves retiree/infrequent-user re-engagement without needing push notifications or the native app first.

#### Cold start — seeded rollout, not all-21-beaches-at-once
- **Launch reports only on the beaches actually visited**: `manasota-key`, `englewood`, `venice`, then `siesta`, `lido` as available. Add `reports_enabled: bool` per key in `BEACH_CONFIG` — flipping on new beaches later (scaling south) is a config change, not a rebuild.
- **Trusted Local Reporter tier**: a small allowlist of verified accounts (founder first) whose reports publish solo even at High severity. Without this, the corroboration rule silently suppresses the founder's own seed reports when there's no second reporter yet at a given beach — the abuse-resistance rule and the bootstrapping need directly conflict unless this override exists.
- **Empty state is the existing UI, unchanged**: the Beach Pulse chip is *absent* (not "0 reports") when nothing exists for a beach — a zero-report beach looks identical to the app today, so the feature can't make a beach feel more broken than before it existed.
- As density grows, Trusted Local Reporter allowlist shrinks in relative importance and can be phased out per-beach once organic corroboration is reliably happening there.

#### Data model (Supabase / Postgres)
```sql
-- reports table
id             uuid primary key default gen_random_uuid()
beach_id       text not null          -- matches BEACH_CONFIG key
report_type    text not null          -- jellyfish | algae | riptide | surf | dead_fish | shark | debris | clarity | crowd | dog | parking | red_tide
severity_tier  text not null          -- low | moderate | high (fixed per report_type, not user-selectable)
notes          text                   -- optional 140-char free text
reporter_id    text not null          -- hashed OAuth subject id (Apple/Google), never plaintext email
trust_tier     text default 'standard' -- standard | trusted_local
status         text default 'published' -- published | pending_corroboration | held_for_review
corroborated_by text[]                -- reporter_ids of corroborating reports, if any
created_at     timestamptz default now()
beach_lat      float                  -- optional, from GPS if user permits
beach_lng      float

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
1. **FAB on beach detail** — "Report conditions" → icon grid, one tap, no form for Low/Moderate; High-tier categories show a brief "this will need a second report to confirm" note inline
2. **Beach Pulse badge** — adjacent to (never inside) the main verdict; absent / neutral-unconfirmed / escalated-confirmed states per the trust model above
3. **Community reports section** in beach detail — chronological list of today's published reports; link to historical trend chart

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

#### Build steps
| Step | Effort | Dependency |
|------|--------|------------|
| Supabase project + `reports` table + RLS | 0.5 day | New: Supabase account |
| Sign in with Apple/Google (Supabase Auth) | 1 day | Supabase; Apple Developer account for App Store anyway |
| `POST /api/reports` + severity-tier publish logic + rate/spike limits | 1 day | Supabase |
| `GET /api/reports/{beach_id}` + integrate into `/api/conditions` response | 0.5 day | above |
| Report FAB + icon-grid bottom sheet UI | 1 day | API ready |
| Beach Pulse badge (adjacent to verdict, 3 states) | 0.5 day | API ready |
| `reports_enabled` per-beach config + seed on 5 beaches | 0.25 day | `BEACH_CONFIG` |
| Daily aggregate job + history endpoint | 0.5 day | reports table |
| Historical trend chart (sparkline) | 1 day | history endpoint |
| **Total estimate** | **~6.75 days** | |

#### Open questions / decisions deferred
- Trusted Local Reporter allowlist mechanics: manual (env var / admin table) is enough for MVP given the 5-beach seed set
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