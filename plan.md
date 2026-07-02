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
- [x] Radar proximity (shipped as old "Phase C" — unrelated to Beach Pulse Phase C) — cyan pulse; separate from official flag
- [x] MCP tools: `get_beach_conditions`, `rank_beaches` (incl. `when=tomorrow`)
- [x] Tide fixes (Sarasota/Manatee stations), cold-start / rank tiers
- [x] Surf period plain-language note; surf paired with shark/water above forecast

---

## Next up (priority order)

### 1. Beach Pulse — user reports (killer differentiator)
**Goal:** the actual bet — fuse NOAA/NWS data with real-time community reports into one trustworthy signal, in a way Mote's broken report flow doesn't. Full spec: *Beach Pulse — full spec* section below. **Developer build guide (accounts → SQL → backend → frontend, with acceptance criteria):** [`docs/handoff-beach-pulse.md`](docs/handoff-beach-pulse.md). Broken into shippable phases, in dependency order:

| Phase | Scope | Effort |
|-------|-------|--------|
| A — Foundation | Supabase project + `reports` table/RLS, **Sign in with Google only** (Apple deferred — see below), `POST /api/reports` with severity-tier publish logic + rate/spike limits | ~2.5 days |
| B — Ship MVP | `GET /api/reports/{beach_id}` + `/api/conditions` integration, Report FAB, Beach Pulse badge (adjacent to verdict), `reports_enabled: true` default across all `BEACH_CONFIG` beaches | ~2 days |
| C — Trust layer | `reporter_beach_standing` table + Local Guide auto-promotion, community reports list with 🏅 marking | ~0.5 day |
| D — Historical (defer) | Daily aggregate job, history endpoint, trend sparkline — lowest priority; needs weeks/months of data to be meaningful regardless of when it's built | ~1.5 days |
| E — Beach info page (new) | Static per-beach amenities: parking (paid/free/none), dog rules, restrooms, lifeguard — curated `BEACH_CONFIG` fields or Google Places, NOT user reports. Owner feedback 2026-07-01: static facts don't belong in the report grid | ~1–2 days |

Phases A+B are the MVP — a beach card with a working, visible Beach Pulse badge. C–E are follow-ons once real usage exists.

**Category decisions (2026-07-01, owner feedback):** `dog` removed from report types (static fact → Phase E); `parking` kept but reframed as real-time "Parking full" (crowd-adjacent signal, genuinely reportable); `wildlife` added (🐬, low tier, optional 140-char note for manatee/whale shark/alligator/etc.) — shark stays its own preset. No open "Other" free-text category: the optional note on wildlife covers the long tail without creating an unmoderated text surface.

### 2. In-app chat — highest product gap
**Goal:** “Best paddle near Venice today?” inside the PWA.

| Step | Effort | Notes |
|------|--------|-------|
| `/api/chat` proxy on Render | ~0.5 day | Keep `GEMINI_API_KEY` server-side |
| React chat drawer / FAB | ~1 day | Calls LLM with function tools → existing API |
| Wire tools: `get_beach_conditions`, `rank_beaches` | ~0.5 day | Already exist on MCP; mirror for HTTP |

**Skip for production:** Streamlit (dev-only). **Optional fast path:** Telegram bot for share-with-family.

### 3. Tomorrow polish (v1.1)
- [ ] Tomorrow **wind** from NWS period text or Open-Meteo (rank still uses current wind obs)
- [ ] Hero **Detailed Forecast** card: show tomorrow period when planning toggle = Tomorrow
- [ ] Dedupe Water & Algae card JSX in `App.tsx` (minor refactor)

### 4. Atlantic coast expansion
- [ ] Add East Coast beaches to `BEACH_CONFIG` (tide stations, NWS points, Mote fallbacks)
- [ ] `coast` filter on `/api/rank` (param exists, not fully used)

### 5. Ops / quality backlog
- [ ] README: align copy (“Today’s outlook” not “Today’s Verdict” everywhere)
- [ ] FWC red tide SSL (`verify=False` workaround)
- [ ] `get_beach_key()` fuzzy-match edge cases (e.g. substring “key”)
- [ ] Hardcoded skywatch events → ephemeris or remove
- [ ] Request-level TTLCache on hot fetchers (`_get_nws_obs`, etc.)
- [ ] `websockets` pinned back to 15.0.1 by `supabase` (its `realtime` sub-package). We don't use Supabase Realtime or any WebSockets and the live deploy is healthy, so it's benign — fix only if a WS/MCP issue surfaces. Options if needed: depend on `postgrest` directly instead of the `supabase` meta-package, or pin `websockets` and test the MCP/SSE stack.

### 6. Later
- [ ] Native iOS (Capacitor + TestFlight) if PWA isn't enough
  - [ ] Lock bundle ID / custom URL scheme early (e.g. `com.marineagent.app`) — Supabase Auth redirect URIs register against it; expensive to change once live
  - [ ] Build `/api/auth/callback` (Beach Pulse spec) transport-agnostic — verify an OAuth identity token, don't assume a web-redirect flow, so swapping web sign-in for a native Capacitor Apple/Google SDK later needs no backend change
  - [ ] Add **Sign in with Apple** here (deferred from Beach Pulse Phase A) — required by App Store guideline 4.8 once native; needs the $99/yr Apple Developer account (also required for submission), a Services ID + signed key in Apple's portal, and periodic client-secret regeneration (Apple keys expire; Google's don't). Tolerate Apple private-relay emails in the digest flow.
  - [ ] Before submitting: add real native capability beyond the webview (push via APNs, native geolocation for report GPS tagging) — a bare Capacitor wrapper around the PWA risks App Store Guideline 4.2 (Minimum Functionality) rejection regardless of how it was built
  - [ ] Home screen widget (WidgetKit, 3 sizes) — content spec drafted, **visual design still needs a real polish pass before rollout, this is layout/content only**:
    - Small — favorite beach only: name, flag-color dot, verdict word, temp + wave
    - Medium — favorite beach (left) + best-nearby pick with distance/reason (right); adds dog-friendly/parking icons since those are top-priority info for regular beach-goers
    - Large — ranked nearby list within radius, favorite beach pinned at top (star marker), Beach Pulse counts shown inline
    - Same rules as in-app: verdict never rewritten by report counts; report escalation is styling-only, no "unconfirmed" text
- [ ] Push notifications for red flag / NWS warnings
- [ ] iMessage — not feasible without Apple Business Chat

---

### Beach Pulse — full spec (priority #1 above)

**Goal:** Beachgoers submit one-tap hazard/condition reports from the beach. The killer-feature bet: fuse NOAA/NWS official data with real-time human eyes-on-the-sand into one trustworthy signal — without becoming Mote's broken, high-friction report flow, and without turning into a second data feed the user has to mentally reconcile. Primary audience: parents/families (repeat, safety-motivated, kids in the water) and retirees/casual goers (infrequent, low patience for friction).

**Core design principle:** the existing go/no-go verdict is never rewritten by reports. Beach Pulse is a separate, adjacent signal — this is the fix for decision-paralysis: one clean verdict, always answerable in 3 seconds, plus an honest "here's what people are seeing" layer next to it.

#### Report categories
| Category | Icon | Severity tier |
|----------|------|----------------|
| Water clarity | 👁️ | Low — publishes on 1 verified report |
| Crowd level | 👥 | Low |
| Wildlife sighting (manatee, gator…) | 🐬 | Low — optional note; shark stays separate |
| Parking full (real-time) | 🅿️ | Low |
| Debris / Trash | 🗑️ | Low |
| Algae / Seaweed | 🌿 | Low — complements FWC HAB data |
| Dead fish | 🐟 | Moderate — often correlates with red tide |
| Rough surf / Waves | 🌊 | Moderate |
| Jellyfish / Man-o-war | 🪼 | Moderate — most common Gulf hazard |
| Riptide / Strong current | 🌀 | **High — panic-capable** |
| Shark sighting | 🦈 | **High — panic-capable** |
| Red tide / toxic water | ☠️ | **High — panic-capable** |

#### Trust model — OAuth sign-in, not email magic-link
- **Web MVP ships Google only.** Apple's "must offer Sign in with Apple" rule (guideline 4.8) only triggers on **App Store submission** — Phases A/B ship as the existing PWA, not a native app, so Google alone is compliant and smaller to build. Sign in with Apple is added in the native iOS phase (it needs the $99/yr Apple Developer account regardless, and Supabase Auth exposes it via the same call — a config add, not a rewrite). See *Native iOS* in section 6.
- One-tap OAuth (Google one-tap) — no typing, no waiting on an inbox. This is what actually fixes Mote's friction (the wait, not the identity).
- A real OAuth identity (vs. disposable email) is the anti-abuse layer: much harder to mass-fake than magic-link emails, which matters most for **High** tier categories that can trigger real panic if spoofed (e.g. a brigaded "shark" report at a packed family beach).
- Rate limit + spike detection per verified account: a burst of identical severe reports from new accounts in a short window auto-holds for review instead of publishing.
- **Visibility vs. escalation are separate — a solo report is never fully hidden.** A single report, any severity, any beach, publishes immediately and is shown as a plain count (e.g. "🦈 1 report") — no "unconfirmed" qualifier text, since a count of 1 already says that; the word would just repeat the number. Corroboration only gates *escalation* to a heavier visual weight (color, not extra copy), not whether it's visible at all. Full suppression (`held_for_review`) is reserved for spike/anomaly detection — a burst of matching reports from new accounts in a short window — which is the actual abuse signature, not "only one person happened to be there." This is what makes it safe to enable reports everywhere from day 1 (see below): there's no density threshold a beach has to clear before its reports "work."
  - **Low** — plain count, neutral styling throughout, no escalation concept needed.
  - **Moderate** — plain count, neutral styling; escalates to a heavier/warmer tone on a 2nd corroborating report or a Local Guide report (see below) — same text, different visual weight.
  - **High** — plain count from the first report (so it never reads as broken or ignored); same escalation via styling, not wording. Spike detection, not corroboration, is what can hold one for review.
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
reporter_id    text not null          -- hashed OAuth subject id (Google for MVP; Apple later), never plaintext email
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
POST /api/reports                        -- submit report; always 'published' unless spike-detected → 'held_for_review' (see Server-side rules). Requires Bearer JWT.
GET  /api/reports/{beach_id}             -- today's published reports for a beach
GET  /api/reports/{beach_id}/history     -- aggregates: ?grain=daily|weekly|monthly&lookback=30d (Phase D)
```
Auth is verified per-request via a Supabase JWT `Authorization: Bearer` header on write routes — **no separate `/api/auth/callback` endpoint** (the OAuth callback is handled client-side by Supabase JS). Verifying a bearer token is inherently transport-agnostic — a native iOS client sends the same header. See [`docs/handoff-beach-pulse.md`](docs/handoff-beach-pulse.md) §0 for the full request flow.

#### Server-side rules (Phase A specifics — starting values, tune with real data)
These are the ambiguous, high-lock-in decisions an implementer needs before writing Phase A. All thresholds are first guesses, centralized as constants so they're tunable without a schema change.

**Rate limit (per reporter):** 1 report per `(reporter_id, beach_id, report_type)` per hour, server-enforced. Blocks a single account spamming one category.

**Corroboration window (report_type-specific freshness):** a report is "corroborated" once ≥2 distinct `reporter_id`s submit the same `report_type` at the same beach within the type's freshness window — high-persistence hazards get longer windows:
- Riptide, shark: 2h (time-sensitive, move/leave quickly)
- Jellyfish, surf, dead fish, red tide: 4h
- Low-tier (clarity, crowd, dog, parking, debris, algae): 6h
Corroboration flips a Moderate/High report's `status` to `escalated` (heavier badge styling) and increments each contributing reporter's `corroborated_count`.

**Spike / anomaly hold (abuse signature, not sparse-but-real):** auto-set `status = 'held_for_review'` (hidden from public reads) when ≥5 reports of the same **High**-tier `report_type` at one beach arrive within 15 min *from accounts with 0 prior corroborated reports* (new/low-trust). A Local Guide or an account with prior corroborated history is exempt — that's real signal, not a brigade. Held reports surface in an admin/review queue (moderation UI is a deferred open question).

**RLS policies on `reports`:**
- SELECT (anon + authed): only rows where `status IN ('published','escalated')` — `held_for_review` never leaks.
- INSERT: authenticated only; `reporter_id` must equal the caller's own auth id (can't post as someone else). `severity_tier` and `status` are set server-side, never trusted from the client — no self-escalation, no self-publishing a held report.
- UPDATE / DELETE: denied to all client roles. Status/escalation changes run only via the backend service role.

**`/api/conditions/{beach_id}` gains a `beach_pulse` object** (frontend renders no chip if absent or `counts` empty):
```json
"beach_pulse": {
  "reports_enabled": true,
  "total_today": 4,
  "counts": [
    { "type": "jellyfish", "count": 3, "escalated": true,  "last_report_min_ago": 40 },
    { "type": "riptide",   "count": 1, "escalated": false, "last_report_min_ago": 12 }
  ]
}
```

#### UI integration
1. **FAB on beach detail** — "Report conditions" → icon grid, one tap, no form; every report posts immediately and shows as a plain count, no qualifier copy
2. **Beach Pulse badge** — adjacent to (never inside) the main verdict; absent / plain-count-neutral / plain-count-escalated (styling only, same text) states per the trust model above
3. **Community reports section** in beach detail — chronological list of today's published reports, Local Guide reports marked with 🏅; link to historical trend chart *(chart is Phase D — hide the link until then)*

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
| Sign in with Google (Supabase Auth) — Apple deferred to native iOS phase | 1 day | Supabase; free Google Cloud OAuth client |
| `POST /api/reports` + severity-tier publish logic + rate/spike limits | 1 day | Supabase |
| `GET /api/reports/{beach_id}` + integrate into `/api/conditions` response | 0.5 day | above |
| Report FAB + icon-grid bottom sheet UI | 1 day | API ready |
| Beach Pulse badge (adjacent to verdict, 3 states) | 0.5 day | API ready |
| `reports_enabled: true` default across all `BEACH_CONFIG` entries | trivial | `BEACH_CONFIG` |
| `reporter_beach_standing` table + Local Guide auto-promotion job | 0.5 day | reports table |
| Daily aggregate job + history endpoint | 0.5 day | reports table |
| Historical trend chart (sparkline) | 1 day | history endpoint |
| **Total estimate** | **~6.5 days** (matches phase table: A 2.5 + B 2 + C 0.5 + D 1.5) | |

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
| Database (planned) | Supabase — `reports` table, Sign in with Google auth (Apple later), daily aggregates |

**Key API**
```
GET /api/conditions/{beach_id}
GET /api/rank?activity=paddling&when=today|tomorrow&beach_id=venice&radius_miles=50
GET /api/beaches_with_flags
```

---

## Infra & cost posture (as of 2026-07-01)

Everything runs on free tiers today; nothing needs upgrading to build and ship the Beach Pulse web MVP.

| Service | Role | Plan | Notes |
|---------|------|------|-------|
| Vercel | Frontend (`web/`) | Hobby (free) | Scales with usage; fine at this stage |
| Render | Compute — FastAPI + MCP (`marine_server.py`) | Hobby workspace, $0/mo + compute | **Stays** — Supabase does not replace it (Render hosts all the Python: fetchers, rank, MCP). See discrepancy below. |
| Render Redis | Ephemeral request cache | Free | TTL cache only — not durable storage; unrelated to Beach Pulse's DB need |
| Supabase | Postgres + Auth for Beach Pulse | Free | **Additive, one feature.** Free tier covers early usage. Gotcha: free projects auto-pause after 7 days with zero API requests — any `/api/conditions` traffic keeps it warm |
| Google OAuth | Sign-in for reports | Free | No Google Cloud cost for a standard OAuth client |
| Apple Developer | Sign in with Apple + App Store | **$99/yr** | Only needed at the native iOS / App Store phase — not for the web MVP |

**What Supabase actually provides** (project has no persistent DB today, only Redis-as-cache): (1) Postgres for `reports` / `reporter_beach_standing` / aggregates; (2) Auth — the OAuth handshake + a stable user id for `reporter_id`; (3) Row Level Security enforced at the DB layer. Not using Realtime, Edge Functions, or Storage.

> ⚠️ **Verify before relying:** [`render.yaml`](render.yaml) declares `plan: starter` (a paid ~$7/mo instance type) for the web service, but billing is $0 on the Hobby workspace — meaning the **live service is almost certainly on a free instance and the blueprint is stale/never-synced**. Free Render instances spin down after ~15 min idle (hence the existing cold-start handling). Confirm the actual live instance type in the Render dashboard before assuming either; reconcile `render.yaml` to match once known.

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