# Handoff: Beach Pulse (community reports) — Phases A & B

**Goal:** ship a working, visible community-reports layer on the beach card — one-tap hazard/condition reports fused *beside* (never overwriting) the existing go/no-go verdict.

**Scope of this doc:** Phase A (foundation + auth + write path) and Phase B (read path + UI). Phases C (Local Guide) and D (history/trends) are follow-ons — noted at the end, not built here.

**Why it's built this way:** see `plan.md` → *Beach Pulse — full spec* for product reasoning (trust model, severity tiers, cold-start). This doc is the **how**; `plan.md` is the **why**. Don't re-litigate decisions here — if something seems off, raise it against `plan.md`.

---

## 0. Architecture decision (read first — it shapes everything)

**The FastAPI backend owns all report logic. The frontend uses Supabase only for sign-in.**

```
Browser ──(Google OAuth via Supabase JS)──► gets a JWT
Browser ──(Bearer JWT)──► marine_server.py ──(service role)──► Supabase Postgres
```

- Frontend talks to Supabase **only** to sign in and hold the session. Every report read/write goes to `marine_server.py`, same as all existing data.
- Backend **verifies the JWT** on write routes, then reads/writes Postgres with the Supabase **service-role key** (bypasses RLS — RLS is a defense-in-depth backstop, not the primary gate).
- Consequence: rate-limiting, spike detection, and severity-tier assignment stay in Python — no Postgres triggers/functions needed.
- Consequence: **no `POST /api/auth/callback` endpoint** (the plan.md placeholder). The OAuth callback is handled client-side by Supabase JS; the backend just validates a Bearer token. This is inherently transport-agnostic — a future native iOS client sends the same Bearer JWT, no backend change.

---

## 1. Prerequisites — one-time account setup (human, ~30–45 min)

These require a person at a dashboard; they can't be scripted here. Everything after this section is code/SQL.

### 1a. Supabase project
1. Sign up at [supabase.com](https://supabase.com) (GitHub login is fine).
2. **New project** → region **`us-east-1`** (closest to Florida users + Render), set a strong DB password and save it.
3. Free tier is sufficient. ⚠️ Free projects **auto-pause after 7 days of zero API traffic** — normal beach-page traffic keeps it warm; just know this for quiet stretches.
4. From **Project Settings → API**, copy three values for the env table below:
   - Project URL
   - `anon` public key
   - `service_role` secret key
5. From **Project Settings → API → JWT Settings**, copy the **JWT Secret** (backend uses it to verify tokens).

### 1b. Google OAuth (for Sign in with Google)
1. In [Google Cloud Console](https://console.cloud.google.com): create a project (or reuse one).
2. **APIs & Services → OAuth consent screen** → External → fill app name (**users see this name at sign-in — use the intended consumer name, editable later**), support email, developer email. No sensitive scopes needed (default email/profile).
3. **APIs & Services → Credentials → Create OAuth client ID → Web application**.
   - Authorized redirect URI: `https://<project-ref>.supabase.co/auth/v1/callback` (from your Supabase project).
   - Copy the **Client ID** and **Client secret**.
4. In **Supabase → Authentication → Providers → Google**: paste Client ID + secret, enable.
5. In **Supabase → Authentication → URL Configuration**: set Site URL to `https://marine-agent.vercel.app` and add it to the redirect allow-list (plus `http://localhost:5173` for local dev).

### 1c. Environment variables

| Var | Where it lives | Value / source | Secret? |
|-----|----------------|----------------|---------|
| `SUPABASE_URL` | Render (backend) | Project URL | no |
| `SUPABASE_SERVICE_ROLE_KEY` | Render (backend) | `service_role` key | **yes** |
| `SUPABASE_JWT_SECRET` | Render (backend) | JWT Secret | **yes** |
| `VITE_SUPABASE_URL` | Vercel (web) | Project URL | no |
| `VITE_SUPABASE_ANON_KEY` | Vercel (web) | `anon` key | no (anon is public by design) |

Add to Render via dashboard (or `render.yaml` env with `sync: false` for secrets). Add to Vercel via project env settings. For local dev, mirror into `web/.env.local` (VITE_ vars) and the backend's environment.

---

## 2. Data layer — run in Supabase SQL editor

Paste and run as-is. Idempotent-ish; run once.

```sql
-- reports
create table public.reports (
  id             uuid primary key default gen_random_uuid(),
  beach_id       text not null,                       -- matches BEACH_CONFIG key
  report_type    text not null,                       -- see SEVERITY_TIER keys in §3
  severity_tier  text not null check (severity_tier in ('low','moderate','high')),
  notes          text check (char_length(notes) <= 140),
  reporter_id    uuid not null references auth.users(id),
  status         text not null default 'published'
                 check (status in ('published','escalated','held_for_review')),
  corroborated_by uuid[] not null default '{}',
  created_at     timestamptz not null default now(),
  beach_lat      double precision,
  beach_lng      double precision
);
create index reports_beach_created_idx on public.reports (beach_id, created_at desc);
create index reports_beach_type_created_idx on public.reports (beach_id, report_type, created_at desc);

-- Local Guide standing (Phase C reads/writes this; safe to create now)
create table public.reporter_beach_standing (
  reporter_id        uuid not null references auth.users(id),
  beach_id           text not null,
  corroborated_count int not null default 0,
  is_local_guide     boolean not null default false,
  points             int not null default 0,
  primary key (reporter_id, beach_id)
);

-- RLS (defense-in-depth; backend uses service_role and bypasses this)
alter table public.reports enable row level security;

create policy "read visible reports" on public.reports
  for select using (status in ('published','escalated'));

create policy "insert own reports" on public.reports
  for insert to authenticated
  with check (reporter_id = auth.uid());
-- no update/delete policies → clients cannot edit or remove reports
```

`reporter_id` is the Supabase auth user id (a uuid) — opaque, non-PII, no separate hashing needed. RLS on `insert` pins it to the caller so a client can't post as someone else; `severity_tier` and `status` are always set by the backend, never trusted from a client body.

---

## 3. Backend — `marine_server.py` (Phase A write path + Phase B read path)

### 3a. Dependencies
Add to `requirements.txt`: `supabase` (supabase-py, for DB access) and `pyjwt` (verify tokens). CORS is already `allow_origins=["*"]` at [marine_server.py:1829](../marine_server.py) — no change.

### 3b. Constants (new module `reports.py`, imported by `marine_server.py`)
All tunable in one place — these are starting values from `plan.md`, not sacred.

```python
RATE_LIMIT_PER_HOUR = 1          # per (reporter_id, beach_id, report_type)
SPIKE_COUNT = 5                  # high-tier reports...
SPIKE_WINDOW_MIN = 15            # ...at one beach within this window...
                                 # ...from accounts with 0 prior corroborated reports → held
LOCAL_GUIDE_THRESHOLD = 3        # corroborated reports at a beach → Local Guide (Phase C)

SEVERITY_TIER = {
    "clarity": "low", "crowd": "low", "dog": "low",
    "parking": "low", "debris": "low", "algae": "low",
    "dead_fish": "moderate", "surf": "moderate", "jellyfish": "moderate",
    "riptide": "high", "shark": "high", "red_tide": "high",
}
CORROBORATION_WINDOWS_MIN = {    # type-specific freshness for corroboration/escalation
    "riptide": 120, "shark": 120,                       # time-sensitive
    "jellyfish": 240, "surf": 240, "dead_fish": 240, "red_tide": 240,
    "clarity": 360, "crowd": 360, "dog": 360,
    "parking": 360, "debris": 360, "algae": 360,
}
```

### 3c. JWT verification dependency
A FastAPI dependency that reads `Authorization: Bearer <jwt>`, verifies HS256 against `SUPABASE_JWT_SECRET`, returns the `sub` claim (the user uuid) as `reporter_id`. On failure → `HTTPException(401)`. Reuse the existing `HTTPException` import.

### 3d. New endpoints

```
POST /api/reports
  Auth: Bearer JWT (required) → 401 without
  Body: { beach_id, report_type, notes?, beach_lat?, beach_lng? }
  Server sets: severity_tier = SEVERITY_TIER[report_type], reporter_id = jwt.sub,
               status = 'published' (or 'held_for_review' if spike rule trips)
  Rules (in order):
    1. Validate beach_id ∈ BEACH_CONFIG and report_type ∈ SEVERITY_TIER → 400
    2. Rate limit: if this (reporter_id, beach_id, report_type) has a row < 1h old → 429
    3. Insert. Then run spike check for high-tier: if ≥ SPIKE_COUNT high-tier rows of this
       type at this beach in last SPIKE_WINDOW_MIN min, all from reporters with 0 prior
       corroborated reports → set those rows status='held_for_review'
    4. Return the created report
  Returns: 201 { report }

GET /api/reports/{beach_id}
  Auth: none (public read)
  Returns: today's rows where status in ('published','escalated'), newest first
```

### 3e. Inject `beach_pulse` into existing conditions endpoint
In `get_beach_conditions_api` at [marine_server.py:1909](../marine_server.py), after obtaining the cached dict and before returning, attach:

```python
cached["beach_pulse"] = build_beach_pulse(beach_id)   # from reports.py
```

`build_beach_pulse(beach_id)` returns (frontend renders nothing if `counts` is empty):

```json
{
  "reports_enabled": true,
  "total_today": 4,
  "counts": [
    { "type": "jellyfish", "count": 3, "escalated": true,  "last_report_min_ago": 40 },
    { "type": "riptide",   "count": 1, "escalated": false, "last_report_min_ago": 12 }
  ]
}
```

A report_type is `escalated: true` when ≥2 distinct `reporter_id`s reported it within that type's `CORROBORATION_WINDOWS_MIN` (Phase C also escalates on a Local Guide report). Keep this query cheap — it runs on every conditions fetch; the `reports_beach_type_created_idx` index covers it. Cache per beach for ~60s if needed.

### 3f. `reports_enabled` flag
Add `reports_enabled: true` to every entry in `BEACH_CONFIG` ([marine_server.py:153](../marine_server.py)). All beaches on from day 1 (see plan.md cold-start reasoning). `build_beach_pulse` returns `reports_enabled: false` and no counts when a beach has it off.

---

## 4. Frontend — `web/` (Phase B UI)

### 4a. Dependency + auth
- Add `@supabase/supabase-js` to `web/package.json`.
- Create `web/src/supabase.ts`: init client from `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`.
- Sign-in: `supabase.auth.signInWithOAuth({ provider: 'google' })`. Session persists in localStorage via the SDK. Attach `session.access_token` as `Authorization: Bearer` on `POST /api/reports` calls in `web/src/api.ts`.

### 4b. Three UI surfaces (per plan.md → UI integration)
1. **Report FAB** on beach detail — "Report conditions" → icon grid of the 12 categories, one tap submits (no form). If not signed in, trigger Google sign-in first, then submit. On success, optimistically bump the badge.
2. **Beach Pulse badge** — rendered **adjacent to** (never inside) the existing verdict, from `conditions.beach_pulse.counts`. States: absent (no counts) / neutral (count, `escalated:false`) / escalated (heavier warm styling, `escalated:true`). **Plain count only — no "unconfirmed" text.** Verdict styling/logic is untouched.
3. **Community reports section** on beach detail — chronological list from `GET /api/reports/{beach_id}`. (The trend-chart link is Phase D — omit for now.)

Match existing card styling in `web/src/App.css`. The verdict logic in `App.tsx` must not read `beach_pulse` — it's display-only, beside the verdict.

---

## 5. Acceptance criteria (definition of done)

**Phase A (backend + auth):**
- [ ] Google sign-in works in the web app; session persists across reload.
- [ ] `POST /api/reports` with a valid JWT inserts a row; without a JWT → 401.
- [ ] `severity_tier` and `status` are set server-side (ignored if sent in body).
- [ ] 2nd identical report `(reporter_id, beach_id, report_type)` within an hour → 429.
- [ ] 5 high-tier reports of one type at one beach in 15 min from fresh accounts → those rows `held_for_review` and absent from public reads.

**Phase B (read + UI):**
- [ ] `GET /api/conditions/{beach_id}` includes a `beach_pulse` object.
- [ ] Submitting via the FAB makes the badge appear with the correct count.
- [ ] Badge escalates styling once a 2nd distinct reporter corroborates within the window; verdict is visually unchanged throughout.
- [ ] Every `BEACH_CONFIG` beach has `reports_enabled: true`.

---

## 6. Explicitly out of scope for this handoff
- **Sign in with Apple** — deferred to the native iOS phase (needs the $99/yr Apple Developer account; same Supabase call). See plan.md → Native iOS.
- **Phase C** — `reporter_beach_standing` promotion job + 🏅 marking (table is created here; logic is not).
- **Phase D** — daily aggregates, history endpoint, trend sparkline.
- Leaderboard, SMS digest, moderation UI beyond the `held_for_review` state existing in the DB.

---

*Build path: §1 (accounts) → §2 (SQL) → §3 (backend, Phase A) → verify Phase A acceptance → §4 (frontend, Phase B) → verify Phase B acceptance. Ship after Phase B.*
