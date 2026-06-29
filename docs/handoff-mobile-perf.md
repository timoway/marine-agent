# Handoff: Mobile-perf & hardening pass (Tasks #1–3)

**Goal:** cut first-load payload on mobile and make the PWA crash-resistant.
**Scope:** three changes, one shared refactor. No backend changes. No behavior changes for the user beyond faster load.

**Baseline (measured):** `mapbox-gl` ships **469 KB gzipped** and is imported eagerly at the
top of `web/src/App.tsx`, so every visitor downloads the full map engine on first paint even
though the default view is the dashboard and the map lives behind the **Map** tab.

---

## Task 1 — Lazy-load the map (biggest win)

**Problem:** `web/src/App.tsx` imports `mapbox-gl` CSS (line 2) and `react-map-gl/mapbox`
(line 9) at module top. These are in the initial bundle. The map only renders when
`viewMode === 'map'` (App.tsx ~line 494).

**Fix:** extract the map JSX into its own component and load it with `React.lazy` so Mapbox
is fetched only when the user opens the Map tab.

### Steps

1. **Create `web/src/BeachMap.tsx`.** Move into it:
   - `import 'mapbox-gl/dist/mapbox-gl.css'`  (from App.tsx line 2)
   - `import MapGL, { Marker, NavigationControl, Source, Layer } from 'react-map-gl/mapbox'` (line 9)
   - The map markup currently at **App.tsx ~494–560** (the `.map-container-fixed` block:
     radar toggle button, map hint, `<MapGL>` with `<NavigationControl>`, the radar
     `<Source>/<Layer>`, and the `beaches.map(...)` markers).
   - Keep the `Radar`, `Flag`, `Zap` lucide icons used inside that block — import them in `BeachMap.tsx`.

2. **Props interface** — the block reads these from App's scope, so pass them in:

   ```ts
   interface BeachMapProps {
     beaches: Beach[];
     selectedBeach: string;
     selectBeach: (id: string) => void;
     mapFocus: { longitude: number; latitude: number; zoom: number }; // App.tsx:309
     mapZoom: number;            // App.tsx:176
     setMapZoom: (z: number) => void;
     showRadar: boolean;         // App.tsx:175
     setShowRadar: (v: boolean) => void;
   }
   ```
   Move the `Beach` interface to a shared `web/src/types.ts` (or export it from App) so both
   files use one definition. `MAPBOX_TOKEN` (App.tsx:16) can be re-read from
   `import.meta.env.VITE_MAPBOX_TOKEN` inside `BeachMap.tsx`.

3. **In `App.tsx`**, replace the moved block with a lazy import + Suspense:

   ```tsx
   import { lazy, Suspense } from 'react';
   const BeachMap = lazy(() => import('./BeachMap'));
   ```
   ```tsx
   ) : viewMode === 'map' ? (
     <Suspense fallback={<div className="map-loading"><div className="spinner">🗺️</div></div>}>
       <BeachMap
         beaches={beaches}
         selectedBeach={selectedBeach}
         selectBeach={selectBeach}
         mapFocus={mapFocus}
         mapZoom={mapZoom}
         setMapZoom={setMapZoom}
         showRadar={showRadar}
         setShowRadar={setShowRadar}
       />
     </Suspense>
   ) : loading ? (
   ```
   Remove the now-dead imports (`mapbox-gl` css, `react-map-gl/mapbox`, and any map-only
   icons) from `App.tsx`. TypeScript will flag unused imports — let it guide cleanup.

4. **Add a `.map-loading` style** in `web/src/index.css` mirroring `.loading-spinner` so the
   tab swap doesn't flash empty.

### Acceptance criteria
- `npm run build` produces a **separate chunk** for mapbox/react-map-gl (a `BeachMap-*.js`
  and a `mapbox-gl-*.js` that are NOT loaded by `index.html`).
- Initial `index-*.js` shrinks by roughly the mapbox weight (~470 KB gzip off first load).
- Dashboard renders with no Mapbox in the network tab; tapping **Map** then fetches it once
  and caches it. Switching back and forth does not refetch.
- Radar toggle, markers, marker labels (zoom ≥ 9), storm badges, and beach selection all
  still work.

---

## Task 2 — Restrict the Mapbox token

**Problem:** `VITE_MAPBOX_TOKEN` is compiled into client JS (App.tsx:16) and is therefore
public. An unrestricted token can be scraped and run up your Mapbox bill.

**Fix (dashboard, no code):**
1. In the [Mapbox account → Access tokens](https://account.mapbox.com/access-tokens/), open
   the token used for production.
2. Add a **URL restriction** allowlist: `https://marine-agent.vercel.app/*` (plus any preview
   domain you use, e.g. `https://*.vercel.app/*` for Vercel previews, and `http://localhost:5173/*`
   for local dev).
3. Confirm scopes are read-only public styles (`styles:read`, `fonts:read`, `tiles:read`) —
   no secret scopes.
4. If the current token was ever committed or shared, **rotate it**: create a new restricted
   token, update `VITE_MAPBOX_TOKEN` in Vercel env (Production + Preview) and in
   `web/.env.local`, redeploy, then delete the old token.

### Acceptance criteria
- Production map still renders.
- The token, if pasted into a curl/Mapbox call from a non-allowlisted origin, is rejected.

---

## Task 3 — React error boundary

**Problem:** there is no error boundary. A single render throw white-screens the whole PWA
with no recovery path — bad on mobile where users can't easily open devtools.

**Fix:** add a top-level class error boundary and wrap `<App />`.

### Steps
1. Create `web/src/ErrorBoundary.tsx` — a class component implementing
   `getDerivedStateFromError` + `componentDidCatch`. The fallback UI should match the app's
   dark theme and offer a **Reload** button (`window.location.reload()`), mirroring the
   existing `.retry-btn` / error styles already in `index.css` (see the API-error block near
   App.tsx:490). Log the error in `componentDidCatch` (console for now; swap for Sentry later).
2. In `web/src/main.tsx`, wrap the tree:

   ```tsx
   import ErrorBoundary from './ErrorBoundary';
   // ...
   createRoot(document.getElementById('root')!).render(
     <StrictMode>
       <ErrorBoundary>
         <App />
       </ErrorBoundary>
     </StrictMode>,
   )
   ```
3. Recommended: wrap the lazy `<BeachMap>` Suspense from Task 1 in its own boundary too, so a
   map failure (e.g. bad token, Mapbox outage) degrades to "Map unavailable" instead of
   taking down the dashboard.

### Acceptance criteria
- Temporarily throwing inside a component shows the fallback UI + working Reload button
  instead of a blank screen. (Remove the test throw before commit.)
- Normal app behavior is unchanged.

---

## Verification (all three)

```bash
cd web
npm run build        # must pass tsc -b + vite build with no type errors
npm run lint
npm run preview      # smoke-test dashboard + map tab on a mobile viewport
```

- In Chrome DevTools (device toolbar, "Fast 4G" throttle): confirm the dashboard is
  interactive before any mapbox chunk loads, and that the mapbox chunk loads only on first
  Map-tab open.
- Run Lighthouse (mobile) before/after — expect a meaningful jump in Performance / reduced
  "Total Blocking Time" and "JS payload."

## Out of scope (do NOT touch in this pass)
- No backend / `marine_server.py` changes.
- No new features (chat, geolocation) — those are separate plan.md items.
- Don't refactor the rest of the 881-line `App.tsx` beyond what Task 1 requires; keep the
  diff reviewable.

## Suggested commits
1. `refactor(web): extract BeachMap and lazy-load mapbox` (Task 1)
2. `feat(web): add top-level error boundary` (Task 3)
3. Task 2 is dashboard config — note the token rotation in the PR description, no code commit
   unless env files change.
