import { lazy, Suspense, useState, useEffect, useMemo } from 'react';
import { 
  Waves, Thermometer, Eye, Droplets, AlertTriangle, 
  Ship, Calendar, Search, Menu, X, LayoutDashboard, Map as MapIcon,
  Activity, Palette, Leaf, Moon, CloudSun, Navigation2,
  TrendingUp, TrendingDown, Flag, ChevronRight, Footprints, Zap, Home, Heart
} from 'lucide-react';
import InstallPrompt from './InstallPrompt';
import ErrorBoundary from './ErrorBoundary';
import { apiFetch, waitForApiReady } from './api';
import { useMediaQuery } from './useMediaQuery';
import { formatFloridaTime } from './format';
import type { Beach, BeachPulse, BeachAmenities } from './types';
import { BeachPulseBadge, ReportFab, CommunityReports, useSession } from './BeachPulse';
import { AccountMenu } from './AccountMenu';
import { OnboardingSheet } from './Onboarding';
import { AmenitiesRow } from './Amenities';
import { useFavorites } from './favorites';
import { distanceMiles, type Coords } from './geo';
import { supabase } from './supabase';

const BeachMap = lazy(() => import('./BeachMap'));

// --- CONFIGURATION ---
const REFRESH_MS = 5 * 60 * 1000; // match backend sync interval
const RADAR_REFRESH_MS = 60 * 1000;

type RankActivity = 'paddling' | 'swimming' | 'beach';

interface RankResult {
  rank: number;
  beach_id: string;
  name: string;
  rank_tier: 'best' | 'radar' | 'caution' | 'warning' | 'avoid';
  activity_status: string;
  wind_mph: number;
  surf_ft: number;
  distance_miles?: number;
}

interface RankResponse {
  activity: RankActivity;
  when?: PlanningHorizon;
  nearby?: {
    anchor_beach_id: string | null;
    anchor_name: string;
    radius_miles: number;
    radius_expanded: boolean;
  };
  results: RankResult[];
}

const RANK_RADIUS_MILES = 50;
const AMENITY_FILTER_RADIUS_MILES = 100; // ~2hr drive, day-trip range
const HOME_BEACH_KEY = 'marineagent-home-beach';
const ONBOARDED_KEY = 'marineagent-onboarded';
const RANK_ACTIVITY_LABELS: Record<RankActivity, string> = {
  paddling: 'Paddle',
  swimming: 'Swim',
  beach: 'Beach',
};

type PlanningHorizon = 'today' | 'tomorrow';

const RANK_DOG_KEY = 'marineagent-rank-dog-friendly';
const RANK_PARKING_KEY = 'marineagent-rank-free-parking';

function readStoredFlag(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
}

function storeFlag(key: string, value: boolean) {
  try {
    localStorage.setItem(key, value ? '1' : '0');
  } catch { /* private mode */ }
}

function readStoredHomeBeach(): string | null {
  try {
    return localStorage.getItem(HOME_BEACH_KEY);
  } catch {
    return null;
  }
}

function storeHomeBeach(beachId: string) {
  localStorage.setItem(HOME_BEACH_KEY, beachId);
}

function activityStatus(
  activities: MarineData['outlook']['activities'] | undefined,
  key: keyof MarineData['outlook']['activities'],
): string {
  const val = activities?.[key];
  if (!val) return 'Red';
  return typeof val === 'string' ? val : val.status;
}

function activityReason(
  activities: MarineData['outlook']['activities'] | undefined,
  key: keyof MarineData['outlook']['activities'],
): string | null {
  const val = activities?.[key];
  if (!val || typeof val === 'string') return null;
  return val.reason;
}

interface SourceMeta {
  fetched_at?: string;
  ok?: boolean;
  stale?: boolean;
  source_url?: string;
  error?: string;
}

interface DataQuality {
  unknown_sources?: string[];
  has_unknowns?: boolean;
  stale?: boolean;
  age_seconds?: number;
  disclaimer?: string;
  cached_from_redis?: boolean;
}

interface MarineData {
  beach: string;
  lat: number;
  lon: number;
  timestamp: string;
  tides: { predictions: any[]; water_temp: string; water_temp_source?: string; current_status: string; trend: string; next_event: string; source: string; meta?: SourceMeta; };
  forecast: { summary: string; rip_current: string; source: string; meta?: SourceMeta; };
  skywatch: { moon_phase: string; illumination: string; planets_visible: string; upcoming_event: string; };
  surf: { height: number; period: number; period_note?: string; intensity: string; type: string; rip_current: string; };
  weather: { temp_f: number | null; wind_mph: number | null; wind_dir: string; meta?: SourceMeta; };
  red_tide: { status: string; meta?: SourceMeta; };
  mote_extras: { water: string; algae: string; algae_type: string; jellyfish?: string; meta?: SourceMeta; };
  outlook: OutlookShape;
  outlook_tomorrow?: OutlookShape;
  teeth: { score: number; label: string; tip: string; } | null;
  clarity: { label: string; feet: number; };
  data_quality?: DataQuality;
  beach_pulse?: BeachPulse;
  amenities?: BeachAmenities | null;
}

function redTideColor(status: string | undefined): string {
  if (status === 'Unknown') return '#facc15';
  if (status && status !== 'Not Present') return '#f87171';
  return '#4ade80';
}

function ripCurrentColor(rip: string | undefined): string {
  if (!rip || rip === 'Unknown') return '#facc15';
  if (rip.includes('High')) return '#f87171';
  return '#4ade80';
}

type OutlookShape = {
    label: string; 
    vibe: string; 
    reason: string; 
    color: string;
    verdict_title?: string;
    plan_label?: string;
    water_now?: { label: string; vibe: string; color: string; summary: string; };
    plan_today?: {
      status: string;
      color: string;
      headline: string;
      forecast: string;
      hourly?: string;
      hourly_lines?: { time: string; forecast: string; rain_chance: number | null; }[];
    };
    verdict?: { headline: string; status: string; color: string; reason: string; };
    activities: {
      paddling: { status: string; reason: string; } | string;
      swimming: { status: string; reason: string; } | string;
      beach: { status: string; reason: string; } | string;
    };
    activities_summary?: string | null;
    storm_badge?: boolean;
    radar_nearby?: boolean;
    radar_proximity?: { max_dbz: number; level: string; storm_nearby: boolean; radius_miles: number; };
    active_alerts?: { event: string; headline: string; severity?: string; }[];
};

function App() {
  const [beaches, setBeaches] = useState<Beach[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [homeBeach, setHomeBeach] = useState<string | null>(() => readStoredHomeBeach());
  const [selectedBeach, setSelectedBeach] = useState<string>(() => readStoredHomeBeach() ?? 'venice');
  const [data, setData] = useState<MarineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMobile = useMediaQuery('(max-width: 1024px)');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [viewMode, setViewMode] = useState<'dashboard' | 'map'>('dashboard');
  const [showRadar, setShowRadar] = useState(false);
  const [mapZoom, setMapZoom] = useState(8.2);
  const [planningHorizon, setPlanningHorizon] = useState<PlanningHorizon>('today');
  const [rankActivity, setRankActivity] = useState<RankActivity>('paddling');
  const [rankData, setRankData] = useState<RankResponse | null>(null);
  const [rankDogFriendly, setRankDogFriendlyState] = useState<boolean>(() => readStoredFlag(RANK_DOG_KEY));
  const [rankFreeParking, setRankFreeParkingState] = useState<boolean>(() => readStoredFlag(RANK_PARKING_KEY));
  const setRankDogFriendly = (updater: boolean | ((v: boolean) => boolean)) => {
    setRankDogFriendlyState(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      storeFlag(RANK_DOG_KEY, next);
      return next;
    });
  };
  const setRankFreeParking = (updater: boolean | ((v: boolean) => boolean)) => {
    setRankFreeParkingState(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      storeFlag(RANK_PARKING_KEY, next);
      return next;
    });
  };
  const [rankLoading, setRankLoading] = useState(false);
  const [rankError, setRankError] = useState<string | null>(null);
  const [wakingUp, setWakingUp] = useState(false);
  const [wakeMessage, setWakeMessage] = useState('Waking up coastal sensors…');
  const session = useSession();
  const [pulseRefresh, setPulseRefresh] = useState(0);
  const { favorites, toggleFavorite } = useFavorites(session);
  const [userCoords, setUserCoords] = useState<Coords | null>(null);
  const [showOnboarding, setShowOnboarding] = useState<boolean>(() => {
    try {
      const onboarded = localStorage.getItem(ONBOARDED_KEY);
      if (onboarded) return false;
      if (readStoredHomeBeach()) {
        // existing user from before onboarding existed — don't nag them
        localStorage.setItem(ONBOARDED_KEY, '1');
        return false;
      }
      return true;
    } catch {
      return false;
    }
  });

  const finishOnboarding = (beachId: string | null) => {
    try { localStorage.setItem(ONBOARDED_KEY, '1'); } catch { /* private mode */ }
    setShowOnboarding(false);
    if (beachId) {
      storeHomeBeach(beachId);
      setHomeBeach(beachId);
      setSelectedBeach(beachId);
    }
  };

  const onFavoriteClick = (beachId: string) => {
    if (session) {
      toggleFavorite(beachId);
    } else {
      void supabase?.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: window.location.origin },
      });
    }
  };

  const closeSidebar = () => setSidebarOpen(false);
  const openSidebar = () => setSidebarOpen(true);

  const switchView = (mode: 'dashboard' | 'map') => {
    setViewMode(mode);
    if (mode === 'map') closeSidebar();
    else if (!isMobile) setSidebarOpen(true);
  };

  const selectBeach = (beachId: string) => {
    setSelectedBeach(beachId);
    setViewMode('dashboard');
    if (isMobile) closeSidebar();
  };

  const setAsHomeBeach = (beachId: string) => {
    storeHomeBeach(beachId);
    setHomeBeach(beachId);
  };

  useEffect(() => {
    setSidebarOpen(!isMobile);
  }, [isMobile]);

  const refreshMs = showRadar ? RADAR_REFRESH_MS : REFRESH_MS;
  const maxAgeParam = showRadar ? '&max_age=60' : '';

  useEffect(() => {
    const fetchBeaches = () => {
      apiFetch<Beach[]>(`/beaches_with_flags${showRadar ? '?max_age=60' : ''}`)
        .then(setBeaches)
        .catch(err => console.error(err));
    };
    fetchBeaches();
    const interval = setInterval(fetchBeaches, refreshMs);
    return () => clearInterval(interval);
  }, [showRadar, refreshMs]);

  useEffect(() => {
    let cancelled = false;

    const fetchConditions = async (showLoading: boolean) => {
      if (showLoading) {
        setLoading(true);
        setError(null);
        setWakingUp(true);
        setWakeMessage('Waking up coastal sensors…');
      }
      try {
        if (showLoading) {
          await waitForApiReady();
          if (cancelled) return;
          setWakeMessage('Loading beach conditions…');
        }
        const json = await apiFetch<MarineData>(
          `/conditions/${selectedBeach}${maxAgeParam ? `?${maxAgeParam.slice(1)}` : ''}`,
        );
        if (cancelled) return;
        if ('error' in json && json.error) throw new Error(String(json.error));
        setData(json);
        setLoading(false);
        setWakingUp(false);
        if (showLoading && isMobile) closeSidebar();
      } catch (err) {
        if (cancelled) return;
        if (showLoading) {
          setError(err instanceof Error ? err.message : 'Failed to load beach data');
          setLoading(false);
          setWakingUp(false);
        }
      }
    };

    fetchConditions(true);
    const interval = setInterval(() => { fetchConditions(false); }, refreshMs);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedBeach, isMobile, showRadar, refreshMs, maxAgeParam]);

  // After a report is submitted, silently refresh the badge. beach_pulse is
  // recomputed server-side on every /conditions call, so a cached fetch (fast)
  // still returns an up-to-date pulse.
  useEffect(() => {
    if (pulseRefresh === 0) return;
    let cancelled = false;
    apiFetch<MarineData>(`/conditions/${selectedBeach}?max_age=600`, { retries: 1 })
      .then(json => { if (!cancelled && !('error' in json && json.error)) setData(json); })
      .catch(() => { /* badge refresh is best-effort */ });
    return () => { cancelled = true; };
  }, [pulseRefresh, selectedBeach]);

  useEffect(() => {
    let cancelled = false;
    setRankLoading(true);
    setRankError(null);
    const filtering = rankDogFriendly || rankFreeParking;
    const params = new URLSearchParams({
      activity: rankActivity,
      when: planningHorizon,
      beach_id: selectedBeach,
      // "Which nearby beaches have X?" is a browse-by-distance question, not
      // a best-conditions-first one — widen to day-trip range (~2hr drive)
      // instead of staying pinned to the "best nearby today" radius.
      radius_miles: filtering ? String(AMENITY_FILTER_RADIUS_MILES) : String(RANK_RADIUS_MILES),
      limit: filtering ? '25' : '5',
      sort: filtering ? 'distance' : 'condition',
    });
    if (rankDogFriendly) params.set('dog_friendly', 'true');
    if (rankFreeParking) params.set('free_parking', 'true');
    apiFetch<RankResponse>(`/rank?${params}`)
      .then(json => {
        if (!cancelled) {
          setRankData(json);
          setRankLoading(false);
        }
      })
      .catch(err => {
        if (!cancelled) {
          console.error(err);
          setRankData(null);
          setRankError(err instanceof Error ? err.message : 'Could not load rankings');
          setRankLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [selectedBeach, rankActivity, planningHorizon, rankDogFriendly, rankFreeParking]);

  const rankAnchorName = useMemo(() => {
    const beach = beaches.find(b => b.id === selectedBeach);
    return beach?.name ?? rankData?.nearby?.anchor_name ?? 'this area';
  }, [beaches, selectedBeach, rankData?.nearby?.anchor_name]);

  const filteredBeaches = useMemo(() => {
    const filtered = beaches.filter(beach =>
      beach.name.toLowerCase().includes(searchQuery.toLowerCase())
    );
    if (!userCoords) return filtered.map(b => ({ ...b, dist: null as number | null }));
    return filtered
      .map(b => ({ ...b, dist: distanceMiles(userCoords, { lat: b.lat, lon: b.lon }) }))
      .sort((a, b) => (a.dist ?? 0) - (b.dist ?? 0));
  }, [beaches, searchQuery, userCoords]);

  const lastUpdated = useMemo(() => {
    if (!data?.timestamp) return null;
    return formatFloridaTime(data.timestamp);
  }, [data?.timestamp]);

  const mapFocus = useMemo(() => {
    const beach = beaches.find(b => b.id === selectedBeach);
    if (beach) return { latitude: beach.lat, longitude: beach.lon, zoom: 9.2 };
    return { latitude: 27.1, longitude: -82.4, zoom: 8.2 };
  }, [beaches, selectedBeach]);

  const planOutlook = useMemo(() => {
    if (planningHorizon === 'tomorrow' && data?.outlook_tomorrow) {
      return data.outlook_tomorrow;
    }
    return data?.outlook ?? null;
  }, [data, planningHorizon]);

  const waterOutlook = data?.outlook ?? null;

  return (
    <div className="dashboard-container">
      <InstallPrompt />
      {showOnboarding && beaches.length > 0 && (
        <OnboardingSheet
          beaches={beaches}
          onPick={beachId => finishOnboarding(beachId)}
          onSkip={() => finishOnboarding(null)}
          onCoords={setUserCoords}
        />
      )}
      {sidebarOpen && isMobile && (
        <div className="sidebar-overlay" onClick={closeSidebar} aria-hidden="true" />
      )}

      <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'} ${isMobile ? 'sidebar-drawer' : ''}`} aria-label="Beach navigation">
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <Ship color="#38bdf8" size={22} />
            <div>
              <h2 className="sidebar-title">MarineAgent</h2>
              <p className="sidebar-subtitle">SWFL Coastal Intel</p>
            </div>
          </div>
          <div className="sidebar-header-actions">
            <AccountMenu session={session} beaches={beaches} favorites={favorites} onSelectBeach={selectBeach} />
            <button onClick={closeSidebar} className="sidebar-close-btn" aria-label="Close menu">
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="view-toggle">
          <button className={`toggle-btn ${viewMode === 'dashboard' ? 'active' : ''}`} onClick={() => switchView('dashboard')}>
            <LayoutDashboard size={14} /> Dashboard
          </button>
          <button className={`toggle-btn ${viewMode === 'map' ? 'active' : ''}`} onClick={() => switchView('map')}>
            <MapIcon size={14} /> Map
          </button>
        </div>

        <div className="rank-panel">
          <div className="rank-panel-header">
            <span className="rank-panel-title">
              Best nearby {planningHorizon === 'tomorrow' ? 'tomorrow' : 'today'}
            </span>
            <span className="rank-panel-subtitle">
              Within {rankData?.nearby?.radius_miles ?? RANK_RADIUS_MILES} mi of {rankAnchorName}
              {rankData?.nearby?.radius_expanded ? ' (expanded)' : ''}
            </span>
          </div>
          <div className="planning-horizon-chips">
            {(['today', 'tomorrow'] as PlanningHorizon[]).map(horizon => (
              <button
                key={horizon}
                type="button"
                className={`rank-chip ${planningHorizon === horizon ? 'active' : ''}`}
                onClick={() => setPlanningHorizon(horizon)}
              >
                {horizon === 'today' ? 'Today' : 'Tomorrow'}
              </button>
            ))}
          </div>
          <div className="rank-activity-chips">
            {(Object.keys(RANK_ACTIVITY_LABELS) as RankActivity[]).map(activity => (
              <button
                key={activity}
                type="button"
                className={`rank-chip ${rankActivity === activity ? 'active' : ''}`}
                onClick={() => setRankActivity(activity)}
              >
                {RANK_ACTIVITY_LABELS[activity]}
              </button>
            ))}
          </div>
          <div className="rank-filter-chips">
            <button
              type="button"
              className={`rank-chip rank-filter-chip ${rankDogFriendly ? 'active' : ''}`}
              onClick={() => setRankDogFriendly(v => !v)}
            >
              🐕 Dog-friendly
            </button>
            <button
              type="button"
              className={`rank-chip rank-filter-chip ${rankFreeParking ? 'active' : ''}`}
              onClick={() => setRankFreeParking(v => !v)}
            >
              🅿️ Free parking
            </button>
          </div>
          {rankLoading ? (
            <p className="rank-empty">Updating rankings…</p>
          ) : rankData?.results?.length ? (
            <div className="rank-list">
              {rankData.results.map(result => (
                <button
                  key={result.beach_id}
                  type="button"
                  className={`rank-item ${selectedBeach === result.beach_id ? 'active' : ''} tier-${result.rank_tier}`}
                  onClick={() => selectBeach(result.beach_id)}
                >
                  <span className="rank-number">{result.rank}</span>
                  <span className="rank-item-body">
                    <span className="rank-item-name">{result.name}</span>
                    <span className="rank-item-meta">
                      <span className={`dot ${result.activity_status}`} />
                      {result.activity_status} · {result.wind_mph} mph · {result.surf_ft} ft
                      {result.distance_miles != null ? ` · ${result.distance_miles} mi` : ''}
                    </span>
                  </span>
                  {result.rank_tier !== 'best' && (
                    <span className={`rank-tier-badge ${result.rank_tier}`}>
                      {result.rank_tier === 'avoid' ? 'Red tide'
                        : result.rank_tier === 'warning' ? 'NWS alert'
                        : result.rank_tier === 'radar' ? 'Radar'
                        : 'Caution'}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ) : (
            <p className="rank-empty">
              {rankError ?? 'No ranked beaches in range yet.'}
            </p>
          )}
        </div>

        <div className="search-container">
          <Search size={16} className="search-icon" />
          <input
            type="text"
            placeholder="Search beaches..."
            className="search-input"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="beach-list">
          {filteredBeaches.map(beach => (
            <button
              key={beach.id}
              type="button"
              className={`beach-item ${selectedBeach === beach.id ? 'active' : ''}`}
              onClick={() => selectBeach(beach.id)}
            >
              <div className="beach-item-dot" style={{ backgroundColor: beach.color }} />
              <span className="beach-item-name">{beach.name}</span>
              {beach.dist != null && <span className="beach-item-dist">{Math.round(beach.dist)} mi</span>}
              {favorites.includes(beach.id) && <Heart size={13} className="beach-item-fav" aria-label="Favorite" />}
              {homeBeach === beach.id && <Home size={14} className="beach-item-home" aria-label="Home beach" />}
              <ChevronRight size={16} className="beach-item-chevron" />
            </button>
          ))}
        </div>

        {isMobile && (
          <p className="sidebar-hint">Tap outside or ✕ to close</p>
        )}
      </aside>

      <div className="main-content">
        {isMobile && (
          <header className="mobile-top-bar">
            <button className="top-bar-btn" onClick={openSidebar} aria-label="Open beach menu">
              <Menu size={22} />
            </button>
            <div className="top-bar-center">
              <span className="top-bar-eyebrow">Coastal Intel</span>
              <span className="top-bar-title">{data?.beach ?? 'MarineAgent'}</span>
            </div>
            <button
              className={`top-bar-btn ${viewMode === 'map' ? 'active' : ''}`}
              onClick={() => switchView(viewMode === 'map' ? 'dashboard' : 'map')}
              aria-label={viewMode === 'map' ? 'Show dashboard' : 'Show map'}
            >
              {viewMode === 'map' ? <LayoutDashboard size={20} /> : <MapIcon size={20} />}
            </button>
            <AccountMenu session={session} beaches={beaches} favorites={favorites} onSelectBeach={selectBeach} />
          </header>
        )}

        {!isMobile && !sidebarOpen && (
          <button className="floating-menu-btn" onClick={openSidebar} aria-label="Open menu">
            <Menu size={24} />
          </button>
        )}

        {error ? (
          <div className="error-container">
            <AlertTriangle size={48} color="#f87171" />
            <h2>Can't Load Beach Data</h2>
            <p>{error}</p>
            <p style={{ opacity: 0.75, fontSize: '0.9rem', maxWidth: '420px', textAlign: 'center' }}>
              Production needs the Render API at <code>marine-agent.onrender.com</code>. First load after idle may take 30–60s to wake up.
            </p>
            <button onClick={() => window.location.reload()} className="retry-btn">Retry</button>
          </div>
        ) : viewMode === 'map' ? (
          <ErrorBoundary
            title="Map unavailable"
            message="The map could not load. You can still use the dashboard, or reload to try again."
          >
            <Suspense fallback={
              <div className="map-loading">
                <div className="spinner">🗺️</div>
              </div>
            }>
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
          </ErrorBoundary>
        ) : loading ? (
          <div className="skeleton-page" aria-busy="true" aria-label="Loading beach conditions">
            <div className="skeleton-block skeleton-meta" />
            <div className="skeleton-block skeleton-hero">
              {wakingUp && <p className="wake-message">{wakeMessage}</p>}
              {wakingUp && <p className="wake-hint">First load after idle can take up to 60 seconds on Render.</p>}
            </div>
            <div className="skeleton-chips">
              <span className="skeleton-block" /><span className="skeleton-block" /><span className="skeleton-block" />
            </div>
            <div className="skeleton-pair">
              <div className="skeleton-block skeleton-card" />
              <div className="skeleton-block skeleton-card" />
            </div>
          </div>
        ) : data ? (
          <>
            {(data.data_quality?.has_unknowns || data.data_quality?.stale) && (
              <div className="safety-banner" role="status">
                <AlertTriangle size={16} />
                <div>
                  {data.data_quality?.has_unknowns && (
                    <p>
                      Some sensors are unavailable
                      {data.data_quality.unknown_sources?.length
                        ? ` (${data.data_quality.unknown_sources.join(', ')})`
                        : ''}
                      . Check official sources before entering the water.
                    </p>
                  )}
                  {data.data_quality?.stale && (
                    <p>Conditions may be stale ({Math.round(data.data_quality.age_seconds ?? 0)}s old).</p>
                  )}
                </div>
              </div>
            )}

            <p className="safety-disclaimer">
              {data.data_quality?.disclaimer ?? 'Advisory only — verify official beach flags, lifeguards, and NWS alerts before entering the water.'}
            </p>

            <div className="header mobile-header">
              <div className="header-row">
                <div className="header-main">
                  <div className="beach-meta beach-meta-compact">
                    <span className="meta-item meta-water">
                      <Droplets size={14} /> {data.tides?.water_temp ?? '--'}°F water
                    </span>
                    <span className="meta-item meta-tide">
                      <Activity size={14} />
                      {data.tides?.next_event ?? '--'}
                      {data.tides?.trend === 'Rising'
                        ? <TrendingUp size={14} />
                        : <TrendingDown size={14} />}
                    </span>
                    <span className="meta-item"><Thermometer size={14} /> {data.weather?.temp_f ?? '--'}°F air</span>
                    <span className="meta-item"><Navigation2 size={14} /> {data.weather?.wind_mph ?? '--'} mph {data.weather?.wind_dir ?? ''}</span>
                    {lastUpdated && <span className="meta-item meta-muted">Updated {lastUpdated} (Florida)</span>}
                  </div>
                </div>
                <div className="header-actions">
                  <button
                    type="button"
                    className={`home-beach-btn compact ${favorites.includes(selectedBeach) ? 'favorited' : ''}`}
                    onClick={() => onFavoriteClick(selectedBeach)}
                    title={favorites.includes(selectedBeach) ? 'Remove favorite' : 'Add to favorites'}
                    aria-label={favorites.includes(selectedBeach) ? 'Remove favorite' : 'Add to favorites'}
                  >
                    <Heart size={16} fill={favorites.includes(selectedBeach) ? 'currentColor' : 'none'} />
                  </button>
                  <button
                    type="button"
                    className={`home-beach-btn compact ${homeBeach === selectedBeach ? 'active' : ''}`}
                    onClick={() => setAsHomeBeach(selectedBeach)}
                    title="Set as home beach"
                    aria-label={homeBeach === selectedBeach ? 'Home beach' : 'Set as home beach'}
                  >
                    <Home size={16} />
                  </button>
                  <div className="glass-flag" style={{ borderColor: data.outlook?.color }}>
                    <Flag size={20} color={data.outlook?.color} fill={data.outlook?.color} />
                  </div>
                </div>
              </div>
              <AmenitiesRow amenities={data.amenities} />
            </div>

            <div className="header desktop-only">
              <div className="header-row">
                <div className="header-main">
                  <div className="beach-name-row">
                    <h1 className="beach-name">{data.beach}</h1>
                    <button
                      type="button"
                      className={`home-beach-btn ${homeBeach === selectedBeach ? 'active' : ''}`}
                      onClick={() => setAsHomeBeach(selectedBeach)}
                      title="Set as home beach"
                    >
                      <Home size={15} />
                      {homeBeach === selectedBeach ? 'Home beach' : 'Set home'}
                    </button>
                    <button
                      type="button"
                      className={`home-beach-btn ${favorites.includes(selectedBeach) ? 'favorited' : ''}`}
                      onClick={() => onFavoriteClick(selectedBeach)}
                      title={favorites.includes(selectedBeach) ? 'Remove favorite' : 'Add to favorites'}
                    >
                      <Heart size={15} fill={favorites.includes(selectedBeach) ? 'currentColor' : 'none'} />
                      {favorites.includes(selectedBeach) ? 'Favorited' : 'Add favorite'}
                    </button>
                  </div>
                  <div className="beach-meta">
                    <span className="meta-item"><Thermometer size={16} /> Air: {data.weather?.temp_f ?? '--'}°F</span>
                    <span className="divider">|</span>
                    <span className="meta-item"><Droplets size={16} /> Water: {data.tides?.water_temp ?? '--'}°F</span>
                    <span className="divider">|</span>
                    <span className="meta-item"><Navigation2 size={16} /> Wind: {data.weather?.wind_mph ?? '--'} mph {data.weather?.wind_dir ?? ''}</span>
                    <span className="divider">|</span>
                    <span className="meta-item" style={{ color: '#f8fafc', fontWeight: 700 }}>
                      <Activity size={16} /> {data.tides?.next_event ?? '--'}
                      {data.tides?.trend === 'Rising' ? <TrendingUp size={14} style={{ marginLeft: '4px' }} /> : <TrendingDown size={14} style={{ marginLeft: '4px' }} />}
                    </span>
                    {lastUpdated && (
                      <>
                        <span className="divider">|</span>
                        <span className="meta-item" style={{ opacity: 0.7 }}>Updated {lastUpdated} (Florida)</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="glass-flag" style={{ borderColor: data.outlook?.color }}>
                   <Flag size={20} color={data.outlook?.color} fill={data.outlook?.color} />
                </div>
              </div>
              <AmenitiesRow amenities={data.amenities} />
            </div>

            <div className="grid">
              <div className="card hero-card" style={{ borderLeft: `6px solid ${planOutlook?.verdict?.color ?? planOutlook?.color ?? '#3b82f6'}` }}>
                <div className="card-title"><Calendar size={18} /> {planOutlook?.verdict_title ?? "Today's outlook"}</div>
                <div className="card-value hero-value">{planOutlook?.verdict?.headline ?? planOutlook?.label ?? '--'}</div>
                <div className="card-subvalue reason-text">{planOutlook?.verdict?.reason ?? planOutlook?.reason ?? '--'}</div>

                <div className="outlook-split">
                  <div className="outlook-panel" style={{ borderColor: waterOutlook?.water_now?.color ?? waterOutlook?.color }}>
                    <span className="outlook-panel-label">Water now</span>
                    <span className="outlook-panel-value" style={{ color: waterOutlook?.water_now?.color ?? waterOutlook?.color }}>
                      {waterOutlook?.water_now?.label ?? waterOutlook?.label ?? '--'}
                    </span>
                    <span className="outlook-panel-meta">{waterOutlook?.water_now?.summary ?? waterOutlook?.reason}</span>
                    <span className="outlook-panel-note">Official beach flag</span>
                  </div>
                  <div className="outlook-panel" style={{ borderColor: planOutlook?.plan_today?.color ?? '#64748b' }}>
                    <span className="outlook-panel-label">{planOutlook?.plan_label ?? 'Plan for today'}</span>
                    <span className="outlook-panel-value" style={{ color: planOutlook?.plan_today?.color ?? '#94a3b8' }}>
                      {planOutlook?.plan_today?.status ?? '--'}
                    </span>
                    <span className="outlook-panel-meta">{planOutlook?.plan_today?.headline ?? '--'}</span>
                    {planOutlook?.plan_today?.forecast && (
                      <span className="outlook-panel-note">{planOutlook.plan_today.forecast}</span>
                    )}
                    {planningHorizon === 'today' && planOutlook?.plan_today?.hourly_lines && planOutlook.plan_today.hourly_lines.length > 0 ? (
                      <div className="hourly-forecast">
                        <span className="outlook-panel-note hourly-forecast-label">Next few hours</span>
                        <ul className="hourly-forecast-list">
                          {planOutlook.plan_today.hourly_lines.map((line, i) => (
                            <li key={i} className="hourly-forecast-item">
                              <span className="hourly-forecast-time">{line.time}</span>
                              <span className="hourly-forecast-desc">
                                {line.forecast}
                                {line.rain_chance != null && line.rain_chance > 0 && (
                                  <span className="hourly-forecast-rain"> ({line.rain_chance}% chance of rain)</span>
                                )}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : planningHorizon === 'today' && planOutlook?.plan_today?.hourly ? (
                      <span className="outlook-panel-note">Next few hours: {planOutlook.plan_today.hourly}</span>
                    ) : null}
                    {planningHorizon === 'today' && planOutlook?.radar_proximity?.storm_nearby && (
                      <span className="outlook-panel-note">
                        Radar: {planOutlook.radar_proximity.max_dbz} dBZ within {planOutlook.radar_proximity.radius_miles} mi
                      </span>
                    )}
                  </div>
                </div>

                {planOutlook?.active_alerts && planOutlook.active_alerts.length > 0 && (
                  <div className="active-alerts">
                    {planOutlook.active_alerts.map((alert, i) => (
                      <p key={i} className="active-alert-item">
                        <Zap size={14} />
                        <span><strong>{alert.event}:</strong> {alert.headline}</span>
                      </p>
                    ))}
                  </div>
                )}

                <div className="activity-status-line">
                   <div className="status-item">
                      <span className={`dot ${activityStatus(planOutlook?.activities, 'paddling')}`}></span> Paddling
                   </div>
                   <span className="divider-sm">|</span>
                   <div className="status-item">
                      <span className={`dot ${activityStatus(planOutlook?.activities, 'swimming')}`}></span> Swimming
                   </div>
                   <span className="divider-sm">|</span>
                   <div className="status-item">
                      <span className={`dot ${activityStatus(planOutlook?.activities, 'beach')}`}></span> Beach
                   </div>
                </div>
                {planOutlook?.activities_summary ? (
                  <p className="activity-note">{planOutlook.activities_summary}</p>
                ) : (
                  <div className="activity-reasons">
                    {(['paddling', 'swimming', 'beach'] as const).map(key => {
                      const reason = activityReason(planOutlook?.activities, key);
                      if (!reason || activityStatus(planOutlook?.activities, key) === 'Green') return null;
                      return (
                        <p key={key} className="activity-note">
                          <strong>{key.charAt(0).toUpperCase() + key.slice(1)}:</strong> {reason}
                        </p>
                      );
                    })}
                  </div>
                )}
              </div>

              <BeachPulseBadge pulse={data.beach_pulse} />

              <div className="card-pair">
                {data.teeth && (
                  <div className="card teeth-card">
                    <div className="card-title"><Footprints size={18} /> Shark Tooth Hunt</div>
                    <div className="card-value">{data.teeth.label} <span className="teeth-score">{data.teeth.score}/10</span></div>
                    <div className="card-subvalue reason-text">{data.teeth.tip}</div>
                    <div className="source-label">Fossil beaches: Venice, Manasota Key, Caspersen, Nokomis, Englewood</div>
                  </div>
                )}

                <div className="card surf-card">
                  <div className="card-title"><Waves size={18} /> Surf</div>
                  <div className="card-value">{data.surf?.intensity ?? 'Unknown'}</div>
                  <div className="card-subvalue">
                    {data.surf?.type ?? '--'} · {data.surf?.height ?? '--'} ft · {data.surf?.period ?? '--'} sec between waves
                  </div>
                  {data.surf?.period_note && (
                    <div className="surf-note">{data.surf.period_note}</div>
                  )}
                  <div className="activity-list" style={{ marginTop: '12px' }}>
                    <div className="activity-item">
                      <AlertTriangle size={16} color={ripCurrentColor(data.surf?.rip_current)} />
                      <div style={{ fontSize: '0.9rem' }}><strong>Rip Currents:</strong> {data.surf?.rip_current ?? '--'}</div>
                    </div>
                    {data.mote_extras?.jellyfish && data.mote_extras.jellyfish !== 'None' && (
                      <div className="activity-item">
                        <AlertTriangle size={16} color="#a855f7" />
                        <div style={{ fontSize: '0.9rem' }}><strong>Jellyfish:</strong> {data.mote_extras.jellyfish}</div>
                      </div>
                    )}
                  </div>
                </div>

                <div className="card tides-card">
                  <div className="card-title"><Droplets size={18} /> Tides & Water</div>
                  <div className="card-value" style={{ fontSize: '1.4rem' }}>{data.tides?.water_temp ?? '--'}°F</div>
                  {data.tides?.water_temp_source && (
                    <div className="card-subvalue">{data.tides.water_temp_source}</div>
                  )}
                  <div className="tide-list">
                    {data.tides?.predictions?.length > 0 ? data.tides.predictions.map((tide: any, i: number) => (
                      <div key={i} className="tide-item">
                        <span>{tide.type === 'H' ? 'High' : 'Low'}</span>
                        <span style={{ fontWeight: 700 }}>{tide.t.split(' ')[1]}</span>
                      </div>
                    )) : <div className="card-subvalue">No upcoming tides</div>}
                  </div>
                  <div className="source-label">Source: {data.tides?.source ?? '--'}</div>
                </div>

                {!data.teeth && (
                  <div className="card water-algae-card">
                    <div className="card-title"><Palette size={18} /> Water & Algae</div>
                    <div className="card-value" style={{ fontSize: '1.5rem' }}>{data.mote_extras?.water ?? '--'}</div>
                    <div style={{ marginTop: '12px' }}>
                      <div className="activity-item">
                        <Eye size={16} color="#3b82f6" />
                        <div style={{ fontSize: '0.9rem' }}><strong>Visibility:</strong> {data.clarity?.feet ?? '--'} ft ({data.clarity?.label ?? '--'})</div>
                      </div>
                      <div className="activity-item">
                        <Leaf size={16} color="#10b981" />
                        <div style={{ fontSize: '0.9rem' }}><strong>Algae:</strong> {data.mote_extras?.algae ?? '--'} ({data.mote_extras?.algae_type ?? '--'})</div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="card forecast-card">
                <div className="card-title"><CloudSun size={18} /> Detailed Forecast</div>
                <div className="card-value forecast-text">{data.forecast?.summary ?? '--'}</div>
                <div className="source-label">Source: {data.forecast?.source ?? 'NWS'}</div>
              </div>

              {data.teeth && (
                <div className="card water-algae-card">
                  <div className="card-title"><Palette size={18} /> Water & Algae</div>
                  <div className="card-value" style={{ fontSize: '1.5rem' }}>{data.mote_extras?.water ?? '--'}</div>
                  <div style={{ marginTop: '12px' }}>
                    <div className="activity-item">
                      <Eye size={16} color="#3b82f6" />
                      <div style={{ fontSize: '0.9rem' }}><strong>Visibility:</strong> {data.clarity?.feet ?? '--'} ft ({data.clarity?.label ?? '--'})</div>
                    </div>
                    <div className="activity-item">
                      <Leaf size={16} color="#10b981" />
                      <div style={{ fontSize: '0.9rem' }}><strong>Algae:</strong> {data.mote_extras?.algae ?? '--'} ({data.mote_extras?.algae_type ?? '--'})</div>
                    </div>
                  </div>
                </div>
              )}

              <div className="card">
                <div className="card-title"><Moon size={18} /> Skywatch</div>
                <div className="card-value" style={{ fontSize: '1.5rem' }}>{data.skywatch?.moon_phase ?? '--'}</div>
                <div className="card-subvalue" style={{ color: '#3b82f6', fontWeight: 700 }}>{data.skywatch?.illumination ?? '--'} Illum.</div>
              </div>

              <div className="card">
                <div className="card-title"><AlertTriangle size={18} /> Red Tide</div>
                <div className="card-value" style={{ color: redTideColor(data.red_tide?.status) }}>
                  {data.red_tide?.status ?? '--'}
                </div>
                {data.red_tide?.status === 'Unknown' && (
                  <div className="card-subvalue reason-text">
                    FWC data unavailable — check{' '}
                    <a href="https://myfwc.com/research/redtide/statewide/" target="_blank" rel="noopener noreferrer">
                      myfwc.com/redtide
                    </a>{' '}
                    before swimming.
                  </div>
                )}
                {data.red_tide?.meta?.fetched_at && (
                  <div className="source-label">
                    FWC sample {formatFloridaTime(data.red_tide.meta.fetched_at)}
                  </div>
                )}
              </div>

              {data.beach_pulse?.reports_enabled && (
                <CommunityReports beachId={selectedBeach} refreshKey={pulseRefresh} />
              )}
            </div>

            {data.beach_pulse?.reports_enabled && (
              <ReportFab
                beachId={selectedBeach}
                session={session}
                onSubmitted={() => setPulseRefresh(k => k + 1)}
              />
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

export default App;
