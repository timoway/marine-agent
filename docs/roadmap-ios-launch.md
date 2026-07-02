# Roadmap: v1.0 iOS Launch — Product Review & Plan

> **Approved 2026-07-02** with owner decisions: chat → post-launch · cold start → keep-warm now, Render Starter at TestFlight · account deletion → aggregate-then-delete (see §2b) · light theme → full theme. **Still open: app name + domain** (owner; gates bundle ID, privacy URLs, OAuth branding).
>
> Audience: this doc is handoff-ready for a developer or a Claude session (function specs) and a design team or Claude design (design briefs, §7). `plan.md` stays the running state-of-project; this doc is the launch plan. When items ship, check them off here and sync `plan.md`.

---

## 1. Where we are (2026-07-02)

**Proven and live:**
- 21 Gulf beaches with a 3-second go/no-go verdict from official data (NOAA/NWS/Mote/FWC), activity statuses, tides, surf, radar proximity, nearby ranking. PWA on Vercel, FastAPI on Render, Redis cache.
- **Beach Pulse shipped end-to-end** — Google sign-in, one-tap reports (12 categories incl. wildlife-with-note), server-side severity tiers, rate limit + spike hold, verdict-adjacent badge, community list. First real report verified in production.
- Supabase (Postgres + Auth) wired with migrations version-controlled; JWKS-verified JWTs; RLS + explicit grants.

**The core promise works:** *Is today a beach day? → Which beach? → What's the latest from the beach?* All three are answerable today, on free-tier infrastructure.

**What launch exposes (the gaps this plan closes):**

| Gap | Severity | Why |
|---|---|---|
| No account surface: sign-out buried in report sheet; no "my reports"; **no account deletion** | **App Store blocker** | Apple 5.1.1(v) requires in-app account deletion. FK today is NO ACTION — user deletion would literally fail. |
| Render free tier cold start (~30s spin-up after idle) | **Kills the product promise** | "3-second verdict" is the entire pitch. A parent at a red light won't wait 30 seconds. |
| "Near me" never wired | High | `/api/rank` accepts `near_lat/near_lon` — frontend never sends them. Tourists/visitors have no home beach; location is how they get "which beach" answered. |
| Dark-only UI | High (usability, not aesthetics) | Primary use is standing on sand in Florida sun. Dark slate-on-slate is genuinely hard to read outdoors. |
| No privacy policy / terms / support page | App Store + OAuth blocker | Required for App Store listing and Google OAuth verification; competitors ship theirs. |
| No analytics | High | Launch decisions (which beaches, retention, report volume) would be blind. |
| No tests, no CI, unpinned deps | Medium | The `websockets` downgrade already bit once silently. One `pip install` away from a broken deploy. |
| `held_for_review` reports have no review surface | Medium | Spike-held reports go nowhere; founder can't moderate. |
| Dead code: `AGENT_API_KEY` with hardcoded default secret in source | Low (hygiene) | Unused — remove. |

---

## 2. Track 1 — Accounts & identity (App Store blocker)

**Status (2026-07-02): built, deployed, structurally verified.** Migration applied and verified live (grants, FK cascade confirmed via `pg_constraint`; the aggregation SQL itself verified correct against the one real existing report, non-destructively, then cleaned up). Backend (`GET /api/me/reports`, `DELETE /api/me`) live on Render, confirmed rejecting no-auth/bad-token with 401, zero regression on existing endpoints. Frontend (`AccountMenu.tsx`) live on Vercel, both entry points (mobile top bar, desktop sidebar) verified in preview against the live API, `signInWithOAuth` call confirmed generating a correct authorize URL. **Not yet exercised — needs a human, same boundary as Beach Pulse's own launch:** the actual `DELETE /api/me` call end-to-end (aggregation lands correctly + auth user actually deletes + reports cascade). Recommend testing with a **second, throwaway Google account** rather than the primary one, since it's genuinely irreversible.

**Goal:** a user can see who they are, see what they've contributed, leave cleanly, and delete themselves — from an obvious place, not a report sheet.

### 2a. Account menu (frontend)
- Avatar button (32px circle, user's initial or Google avatar) in the header, right side, next to the flag icon. Signed-out state: subtle outline person icon; tapping opens Google sign-in directly.
- Tapping avatar opens a bottom sheet (mobile) / popover (desktop):
  - Email + "Signed in with Google" line
  - **My reports** — reverse-chron list: category icon + label, beach name, relative time, status chip (`published` / `confirmed` / `held`). Read-only v1.
  - **Sign out** (also stays in the report sheet — two paths, one behavior)
  - **Delete account** — destructive styling, one confirm dialog: "This permanently deletes your account and your N reports. This cannot be undone." → calls `DELETE /api/me`.
- Report sheet keeps its existing signed-in row; it just stops being the *only* surface.

### 2b. Backend + schema
- **Deletion policy (owner decision 2026-07-02): aggregate-then-delete.** The historical/forecasting value of reports (YoY "jellyfish season peaks in August at Venice") lives in *counts per beach per category per day*, never in reporter identity — and `severity_tier` is a fixed function of `report_type`, so identity-free aggregates lose zero analytical information.
- Migration (pulls a small slice of Phase D forward):
  - Create `public.daily_report_aggregates` (`beach_id text, report_date date, report_type text, count int, primary key (beach_id, report_date, report_type)`) + service_role grants (remember the §1a toggle lesson — explicit grants required).
  - `alter table` the `reporter_id` FKs on `reports` and `reporter_beach_standing` to `on delete cascade`.
- `DELETE /api/me` — JWT-required: (1) upsert the caller's reports into `daily_report_aggregates` (increment counts, grouped by beach/date/type); (2) delete the Supabase auth user via the admin API with the service role — cascade removes their identified rows. Transactional on the aggregate step. Returns 204; frontend signs out locally and clears state.
- (When Phase D proper lands, a nightly job aggregates *all* reports on a schedule; the on-delete path above stays as the guarantee that deletion never loses history.)
- `GET /api/me/reports` — JWT-required, returns caller's reports (all statuses, incl. held — their own data).
- `POST /api/reports` response unchanged.

### 2c. Sign in with Apple — stays in the native phase (per plan.md), but the account menu above must be built provider-agnostic (show provider name from session, don't hardcode "Google").

**Estimate: ~2.5 days** (incl. the aggregates table). Acceptance: sign out reachable in ≤2 taps from anywhere; deleting an account removes the auth user and all their identified rows *and* their counts appear in `daily_report_aggregates` (verify both via SQL); My Reports shows a just-submitted report.

---

## 3. Track 2 — Speed to verdict (the product promise)

**Goal:** cold open → verdict readable in under 3 seconds, warm; under 8 seconds, worst case.

- **Cold start now:** external keep-warm ping of `/health` every 10 min (cron-job.org or UptimeRobot, free). Document in `render.yaml` comments.
- **Cold start at TestFlight:** upgrade Render to Starter (~$7/mo). Free-tier spin-down is incompatible with a consumer launch; this is the first dollar this project should spend. (Owner decision recorded below.)
- **Skeleton UI:** replace spinner-on-navy with skeleton cards (verdict block, chips row, two card outlines) so paint is instant and the verdict slot is visibly "coming."
- **"Near me":** on first load without a saved home beach, request geolocation with value-first framing (see onboarding, §7). If granted → `/api/rank?near_lat=..&near_lon=..` selects the nearest beach and orders the sidebar by distance. If denied → current behavior (Venice default). Params already exist server-side; this is frontend-only.
- **Onboarding (first run only, skippable, one sheet not a wizard):** (1) location permission ask with the payoff stated — "Find your nearest green flag" — (2) pick/confirm home beach from a distance-sorted list, (3) one line explaining the verdict ("One answer, from NOAA + lifeguard flags + people on the sand"). Never shown again.

**Estimate: ~2 days** (excluding the Render plan change, which is a dashboard click). Acceptance: Lighthouse perf ≥ 85 mobile; verdict visible < 3s on warm API over 4G; first-run flow lands a chosen beach.

---

## 4. Track 3 — Beach knowledge (Phase E, pulled forward)

**Goal:** answer the #2 question ("which beach?") with the facts regular beachgoers actually rank by — parking, dogs, restrooms — which official feeds will never provide and which competitors bury in walls of text.

- Extend `BEACH_CONFIG` per beach: `parking: 'free'|'paid'|'street'|'none'`, `parking_notes` (short), `dog_friendly: bool`, `dog_notes`, `restrooms: bool`, `lifeguard: 'seasonal'|'year_round'|'none'`, `entry_fee`. **Owner curates the 21 beaches** — a day of desk research, no API dependency. (Google Places later if it ever needs to scale; not for 21 beaches.)
- New "Know before you go" block on the beach detail (see design §7c).
- **Rank filters:** "Dog-friendly" and "Free parking" toggles on the nearby-rank panel. *This is the sleeper feature* — "dog-friendly beaches near me with a green flag" is a query no competitor answers in one tap, and it's exactly the persona's question.

**Estimate: ~1.5 days dev + owner curation day.** Acceptance: every beach has the block; rank filters work; no beach shows "unknown" at launch.

---

## 5. Track 4 — Community trust & moderation

- **Moderation runbook first, admin UI later:** `docs/moderation-runbook.md` with copy-paste SQL for: list `held_for_review`, release (`status='published'`), reject (delete), ban-check a reporter's history. Founder-scale for months. Admin UI is explicitly deferred.
- **Phase C (Local Guide auto-promotion)** stays post-launch — needs report volume to mean anything — but ship the **🏅 badge rendering** path in the community list now (it reads `reporter_beach_standing`, which exists), so the trust layer lights up without a frontend release when C lands.
- **Report undo:** 2-minute window after submitting — "Undo" in the success toast → `DELETE /api/reports/{id}` (JWT, own report, created < 2 min ago). Kills the #1 support complaint (fat-fingered category) before it exists, and softens the 1/hour rate limit.

**Estimate: ~1.5 days.**

---

## 6. Track 5 — Launch quality, compliance, hardening

**Compliance (App Store + OAuth gates):**
- `/privacy` and `/terms` static pages (plain, honest: what's collected — email, reports, optional GPS; what's not — no ads, no sale of data). Required for App Store listing and referenced from the Google OAuth consent screen. Add a support contact (mailto or form).
- **Name + domain decision now, not at native phase.** The bundle ID locks at first TestFlight build; the domain feeds privacy-policy URLs, OAuth consent branding (currently shows `mubvodgysgdlxwpzgawg.supabase.co` — functional, but not what a parent should see), and App Store listing. Working name "MarineAgent" reads infrastructure, not consumer. Owner decision; everything else in this plan is name-agnostic.

**Hardening:**
- Pin `requirements.txt` (`pip freeze` into pinned file; the `websockets` downgrade already demonstrated the risk) and commit `package-lock.json` discipline (already present).
- **CI (GitHub Actions):** on PR/push — `tsc -b`, `vite build`, and a `pytest` run of `reports.py` hermetic tests (port the smoke script from scratchpad into `tests/test_reports.py`). ~half a day, catches the whole class of "worked locally."
- Remove dead `AGENT_API_KEY` (unused; hardcoded default secret in source).
- Tighten CORS from `*` to the real origins (vercel.app + localhost + future domain) — low urgency (Bearer auth, no cookies), do it while touching config.
- Known issue to document, not fix: OAuth in *installed-PWA* standalone mode may lose session (storage isolation). Native iOS auth (Capacitor + ASWebAuthenticationSession / native Apple sign-in) resolves it properly; don't burn time on a web workaround.

**Analytics (decide-with-data at launch):**
- Vercel Web Analytics (free, no cookies) for pageviews/uniques.
- Server-side counters (Redis, already present): verdict views per beach, report submissions per category, rank queries. Expose as `/api/stats` (private). No third-party SDK, no consent banner needed.

**Estimate: ~2 days total.**

---

## 7. Design brief (for design team / Claude design)

**Principles:** (1) The verdict is the hero — everything else is supporting cast. (2) Sunlight-first: this app is used outdoors at noon; contrast is a safety feature, not a style choice. (3) Official vs. community signals stay visually distinct (solid/bordered official; softer chips for community — already established by Beach Pulse). (4) Calm, not alarmist: cautions inform, they don't scream. (5) One glance, one answer — resist adding a second competing focal point to any screen.

### 7a. Sunlight (light) theme — full theme, not a contrast patch
- Auto via `prefers-color-scheme`, manual override toggle in the account menu (persisted in `localStorage`).
- Token swap (current dark values → light): page `#0f172a → #f1f5f9`; card `#1e293b → #ffffff` with `#e2e8f0` border; text `#f8fafc → #0f172a`; muted `#94a3b8 → #475569`.
- Verdict/flag/pulse colors keep hue but shift for light-bg contrast: green `#4ade80 → #15803d`, yellow `#facc15 → #a16207`, red `#f87171 → #b91c1c`, blue `#3b82f6 → #1d4ed8`. **WCAG AA 4.5:1 minimum everywhere; 7:1 target for the verdict headline.**
- Deliverable: a token table (CSS custom properties) replacing today's hardcoded hex — one-time refactor that also makes native theming trivial later.

### 7b. Account menu (spec in §2a)
Bottom sheet on mobile, 20px radius top corners matching the report sheet; avatar = 32px circle, brand-blue bg, white initial. Destructive action separated by a divider, red text, never a primary button.

### 7c. "Know before you go" block
A row of 4–5 icon+label facts directly under the beach name header (🅿️ Paid lot · 🐕 No dogs · 🚻 Restrooms · ⛑️ Seasonal): scannable in one sweep, no card chrome, muted color so it never competes with the verdict. Tap → expands notes (parking cost, dog rules detail).

### 7d. Onboarding sheet
One sheet, three stacked moments (not three screens): permission ask with payoff line, distance-sorted beach picker, one-line verdict explainer. Illustration optional; skip always visible top-right.

### 7e. Share card
Web Share API v1: text + link ("Venice Beach today: ✅ Good — green flag, 81° water, calm surf. — via [AppName]"). v2 (post-launch): server-rendered OG image (verdict color band, beach name, flag, temp) so links unfurl beautifully in iMessage/group chats — *this is the growth loop for the parent persona; parents share conditions to family threads.*
Share button placement: subtle icon top-right of the hero verdict card.

### 7f. App identity (needs the name decision)
Brief for designer: coastal + trustworthy + parent-friendly; flag motif is the strongest ownable symbol (the verdict IS a flag); avoid alarm-red as brand color; wordmark must be legible at widget size. Deliverables: icon (iOS sizes), splash, OG default image, favicon set.

### 7g. Home-screen widget — content spec already in `plan.md` §6 "Later"; design pass happens with the native phase, not now.

---

## 8. Track 6 — Native iOS shell (after Tracks 1–5)

Unchanged from `plan.md` (Capacitor + TestFlight, bundle ID lock, Sign in with Apple, APNs push for home-beach red-flag alerts, native geolocation, widget, Guideline 4.2 native-capability bar) — with one sequencing note: **push notifications for home-beach flag changes are the single strongest native hook** ("your beach just went red") and should be the flagship of the native release, not an afterthought.

**Launch playbook (the part that isn't code):**
1. TestFlight beta: 20–50 locals recruited from Sarasota/Venice parent Facebook groups + paddle clubs — the exact persona, zero ad spend.
2. Founder seeds reports daily on the 5 home beaches during beta (cold-start plan from Beach Pulse spec).
3. App Store listing leads with the verdict screenshot, not a feature list — the anti-beacheo positioning. Subtitle: the 3-second answer ("Is today a beach day?").
4. Success metrics (via Track 5 analytics): D7 retention ≥ 25% of beta cohort; ≥ 10 community reports/week across core beaches by week 4; verdict-view → report conversion ≥ 2%; TestFlight feedback themes triaged weekly.

---

## 9. Explicitly NOT doing for v1 (anti-bloat, per owner's founding constraint)

- **In-app chat** — moved post-launch (owner decision below). The verdict + rank + pulse already answer the three core questions; chat is a power-user layer, not launch-critical.
- Leaderboard / points UI (Phase C ships silently, badge only).
- Historical trend charts (Phase D — needs months of data regardless).
- Atlantic coast expansion (focus the 21; expansion dilutes seeding).
- SMS digests, email digests (post-launch; needs the domain first anyway).
- Admin moderation UI (runbook suffices at founder scale).

---

## 10. Sequencing & effort summary

| Order | Track | Effort | Gate |
|---|---|---|---|
| 1 | Accounts & identity (§2) | ~2.5d | App Store blocker; do first |
| 2 | Speed to verdict (§3) | ~2d | Product promise |
| 3 | Beach knowledge (§4) | ~1.5d + owner curation | Differentiator |
| 4 | Community trust (§5) | ~1.5d | Trust layer |
| 5 | Quality/compliance/hardening (§6) | ~2d | App Store gates |
| 6 | Design system + sunlight theme (§7) | ~2–3d | Parallel with 3–5 |
| 7 | Native shell + TestFlight (§8) | ~4–5d | After 1–6 |
| | **Total to TestFlight** | **~15–17 dev days** | |

**Decisions locked 2026-07-02:** chat → post-launch ✓ · keep-warm now, Render Starter at TestFlight ✓ · account deletion → aggregate-then-delete ✓ · full sunlight theme ✓.
**Still open (owner):** **app name + domain** — start now; gates bundle ID (locks at first TestFlight build), privacy URLs, OAuth consent branding, App Store listing.
