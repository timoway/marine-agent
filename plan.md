# Marine Agent — Development Plan & Session Handoff

> **Where to store memory:** Keep project state here in `plan.md` (version-controlled, survives new sessions, agents read it on clone). README `## Roadmap` stays a short public checklist — sync both when shipping. Optional: Grok/Cursor user memory for personal prefs only, not task state.

**Production:** [marine-agent.vercel.app](https://marine-agent.vercel.app) · API [marine-agent.onrender.com](https://marine-agent.onrender.com)  
**Last plan update:** 2026-06-28 · **Latest commit:** see `git log -1`

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

## Architecture quick reference

| Piece | Location |
|-------|----------|
| Outlook / tomorrow logic | `marine_server.py` — `_analyze_*_situation`, `_build_outlook`, `rank_beaches_data` |
| Frontend planning toggle | `web/src/App.tsx` — `planningHorizon`, `planOutlook`, rank panel |
| Home beach | `web/src/App.tsx` — `HOME_BEACH_KEY` |
| Deploy | Vercel (`web/`) + Render (`marine_server.py`, `render.yaml`) |

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