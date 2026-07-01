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

### 6. User Reports — Community Beach Conditions

**Goal:** Beachgoers submit quick hazard/condition reports from the beach. Reports enrich the beach card alongside NOAA/NWS data and build a historical dataset for trend analysis (daily → weekly → monthly → year-over-year).

#### Report categories
| Category | Icon | Notes |
|----------|------|-------|
| Jellyfish / Man-o-war | 🪼 | Most common Gulf hazard |
| Algae / Seaweed | 🌿 | Visual + smell; complements FWC HAB data |
| Riptide / Strong current | 🌀 | High urgency; short persistence |
| Rough surf / Waves | 🌊 | Qualitative from swimmer/paddler POV |
| Dead fish | 🐟 | Often correlates with red tide events |
| Sharks / Wildlife | 🦈 | Sighting report; no severity needed |
| Debris / Trash | 🗑️ | Water quality signal |
| Water clarity | 👁️ | Clear / murky / brown |

#### Trust model (email, no full account)
- User submits report → prompted for email → one-time magic link sent → token stored in `localStorage`
- Subsequent reports skip email prompt (token already stored)
- Rate limit: **1 report per beach per category per email per hour** (server-enforced)
- All reports labeled "Community report" in UI — clearly distinct from official data

#### Data model (Supabase / Postgres)
```sql
-- reports table
id           uuid primary key default gen_random_uuid()
beach_id     text not null          -- matches BEACH_CONFIG key
report_type  text not null          -- jellyfish | algae | riptide | surf | dead_fish | shark | debris | clarity
severity     text                   -- low | moderate | high (optional, user-selectable)
notes        text                   -- optional 140-char free text
reporter_email_hash text           -- sha256(email) — never store plaintext
reporter_token text                -- opaque token sent in magic link, stored locally
verified_at  timestamptz            -- set when user clicks magic link
created_at   timestamptz default now()
beach_lat    float                  -- optional, from GPS if user permits
beach_lng    float

-- daily_report_aggregates (materialized or scheduled view)
beach_id     text
report_date  date
report_type  text
count        int
-- enables YoY / MoM / WoW / daily trend charts
```

#### New API endpoints
```
POST /api/reports                        -- submit report (returns pending if unverified)
GET  /api/reports/{beach_id}             -- today’s verified reports for a beach
GET  /api/reports/{beach_id}/history     -- aggregates: ?grain=daily|weekly|monthly&lookback=30d
GET  /api/reports/verify/{token}         -- magic link callback; marks reports verified
```

#### UI integration — three surfaces
1. **FAB on beach detail** — "Report conditions" button → bottom sheet with icon grid (categories) + optional severity slider + notes → email prompt if no token
2. **Badge on beach card** — e.g. "🪼 4 · 🌀 1 today" inline with flag/alerts
3. **Community reports section** in beach detail — chronological list of today’s verified reports; link to historical trend chart

#### Influence on activity status
- 3+ jellyfish reports (last 4h) → adds caution to Swimming status
- Any riptide report (last 2h) → adds caution to Paddling + Swimming
- 3+ dead fish / algae reports → flags Water card with community signal
- Clear label: "Based on X community reports — not official data"

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
| `POST /api/reports` + email magic link (Supabase Auth or Resend) | 1 day | Supabase |
| `GET /api/reports/{beach_id}` + integrate into `/api/conditions` response | 0.5 day | above |
| Report FAB + bottom sheet UI | 1 day | API ready |
| Badge + community section on beach card | 0.5 day | API ready |
| Influence activity status logic | 0.5 day | reports in conditions payload |
| Daily aggregate job + history endpoint | 0.5 day | reports table |
| Historical trend chart (sparkline) | 1 day | history endpoint |
| **Total estimate** | **~5.5 days** | |

#### Open questions / decisions deferred
- Magic link email provider: Supabase built-in (easiest) vs. Resend (more control over templates)
- Moderation: flag/hide report button? Auto-hide outliers (1 shark report vs. 10 jellyfish)?
- Accounts: Supabase Auth is already wired if magic link is used — upgrading to full accounts later is a config change, not a rewrite

---

## Architecture quick reference

| Piece | Location |
|-------|----------|
| Outlook / tomorrow logic | `marine_server.py` — `_analyze_*_situation`, `_build_outlook`, `rank_beaches_data` |
| Frontend planning toggle | `web/src/App.tsx` — `planningHorizon`, `planOutlook`, rank panel |
| Home beach | `web/src/App.tsx` — `HOME_BEACH_KEY` |
| Deploy | Vercel (`web/`) + Render (`marine_server.py`, `render.yaml`) |
| Database (planned) | Supabase — `reports` table, magic-link auth, daily aggregates |

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