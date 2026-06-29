import { useState, useEffect, useMemo } from 'react';
import 'mapbox-gl/dist/mapbox-gl.css';
import { 
  Waves, Thermometer, Eye, Droplets, AlertTriangle, 
  Ship, Calendar, Search, Menu, X, LayoutDashboard, Map as MapIcon,
  Activity, Palette, Leaf, Moon, CloudSun, Navigation2,
  TrendingUp, TrendingDown, Flag, Radar, ChevronRight, Footprints, Zap
} from 'lucide-react';
import MapGL, { Marker, NavigationControl, Source, Layer } from 'react-map-gl/mapbox';
import InstallPrompt from './InstallPrompt';
import { apiFetch, waitForApiReady } from './api';
import { useMediaQuery } from './useMediaQuery';
import { formatFloridaTime } from './format';

// --- CONFIGURATION ---
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || '';
const REFRESH_MS = 5 * 60 * 1000; // match backend sync interval
const RADAR_REFRESH_MS = 60 * 1000;

interface Beach { id: string; name: string; lat: number; lon: number; color?: string; storm_badge?: boolean; radar_nearby?: boolean; }

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
  nearby?: {
    anchor_beach_id: string | null;
    anchor_name: string;
    radius_miles: number;
    radius_expanded: boolean;
  };
  results: RankResult[];
}

const RANK_RADIUS_MILES = 50;
const RANK_ACTIVITY_LABELS: Record<RankActivity, string> = {
  paddling: 'Paddle',
  swimming: 'Swim',
  beach: 'Beach',
};

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

interface MarineData {
  beach: string;
  lat: number;
  lon: number;
  timestamp: string;
  tides: { predictions: any[]; water_temp: string; water_temp_source?: string; current_status: string; trend: string; next_event: string; source: string; };
  forecast: { summary: string; rip_current: string; source: string; };
  skywatch: { moon_phase: string; illumination: string; planets_visible: string; upcoming_event: string; };
  surf: { height: number; period: number; intensity: string; type: string; rip_current: string; };
  weather: { temp_f: number; wind_mph: number; wind_dir: string; };
  red_tide: { status: string; };
  mote_extras: { water: string; algae: string; algae_type: string; jellyfish?: string; };
  outlook: { 
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
  teeth: { score: number; label: string; tip: string; } | null;
  clarity: { label: string; feet: number; };
}

function App() {
  const [beaches, setBeaches] = useState<Beach[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBeach, setSelectedBeach] = useState<string>('venice');
  const [data, setData] = useState<MarineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isMobile = useMediaQuery('(max-width: 1024px)');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [viewMode, setViewMode] = useState<'dashboard' | 'map'>('dashboard');
  const [showRadar, setShowRadar] = useState(false);
  const [mapZoom, setMapZoom] = useState(8.2);
  const [rankActivity, setRankActivity] = useState<RankActivity>('paddling');
  const [rankData, setRankData] = useState<RankResponse | null>(null);
  const [rankLoading, setRankLoading] = useState(false);
  const [rankError, setRankError] = useState<string | null>(null);
  const [wakingUp, setWakingUp] = useState(false);
  const [wakeMessage, setWakeMessage] = useState('Waking up coastal sensors…');

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

  useEffect(() => {
    let cancelled = false;
    setRankLoading(true);
    setRankError(null);
    const params = new URLSearchParams({
      activity: rankActivity,
      beach_id: selectedBeach,
      radius_miles: String(RANK_RADIUS_MILES),
      limit: '5',
    });
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
  }, [selectedBeach, rankActivity]);

  const rankAnchorName = useMemo(() => {
    const beach = beaches.find(b => b.id === selectedBeach);
    return beach?.name ?? rankData?.nearby?.anchor_name ?? 'this area';
  }, [beaches, selectedBeach, rankData?.nearby?.anchor_name]);

  const filteredBeaches = useMemo(() => beaches.filter(beach => 
    beach.name.toLowerCase().includes(searchQuery.toLowerCase())
  ), [beaches, searchQuery]);

  const lastUpdated = useMemo(() => {
    if (!data?.timestamp) return null;
    return formatFloridaTime(data.timestamp);
  }, [data?.timestamp]);

  const mapFocus = useMemo(() => {
    const beach = beaches.find(b => b.id === selectedBeach);
    if (beach) return { latitude: beach.lat, longitude: beach.lon, zoom: 9.2 };
    return { latitude: 27.1, longitude: -82.4, zoom: 8.2 };
  }, [beaches, selectedBeach]);

  return (
    <div className="dashboard-container">
      <InstallPrompt />
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
          <button onClick={closeSidebar} className="sidebar-close-btn" aria-label="Close menu">
            <X size={20} />
          </button>
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
            <span className="rank-panel-title">Best nearby today</span>
            <span className="rank-panel-subtitle">
              Within {rankData?.nearby?.radius_miles ?? RANK_RADIUS_MILES} mi of {rankAnchorName}
              {rankData?.nearby?.radius_expanded ? ' (expanded)' : ''}
            </span>
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
          <div className="map-container-fixed" style={{ position: 'relative' }}>
             {/* Radar Toggle Overlay */}
             <button 
               className={`radar-toggle ${showRadar ? 'active' : ''}`}
               onClick={() => setShowRadar(!showRadar)}
               title="Toggle NWS Weather Radar"
             >
               <Radar size={20} />
               <span>RADAR</span>
             </button>

             <p className="map-hint">Tap any flag for beach conditions</p>
             <MapGL
               initialViewState={mapFocus}
               onMove={(evt) => setMapZoom(evt.viewState.zoom)}
               style={{ width: '100%', height: '100%' }}
               mapStyle="mapbox://styles/mapbox/navigation-night-v1"
               mapboxAccessToken={MAPBOX_TOKEN}
             >
               <NavigationControl position="top-right" />
               
               {showRadar && (
                 <Source
                   id="nws-radar"
                   type="raster"
                   tiles={['https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png']}
                   tileSize={256}
                 >
                   <Layer
                     id="radar-layer"
                     type="raster"
                     paint={{ 'raster-opacity': 0.6 }}
                   />
                 </Source>
               )}

               {beaches.map(beach => (
                 <Marker
                   key={beach.id}
                   latitude={beach.lat}
                   longitude={beach.lon}
                   anchor="bottom"
                   onClick={e => {
                     e.originalEvent.stopPropagation();
                     selectBeach(beach.id);
                   }}
                 >
                    <div className={`map-marker-pulse ${selectedBeach === beach.id ? 'selected' : ''} ${beach.radar_nearby && !beach.storm_badge ? 'radar-nearby' : ''}`}>
                      {mapZoom >= 9 && (
                        <div className="marker-name-label">{beach.name}</div>
                      )}
                      {beach.storm_badge && (
                        <div className="marker-storm-badge" title="NWS weather warning active">
                          <Zap size={11} fill="#0f172a" stroke="#0f172a" />
                        </div>
                      )}
                      <div className="pulse-ring" style={{ backgroundColor: `${beach.color}44` }}></div>
                      <div className="pulse-dot" style={{ backgroundColor: beach.color }}></div>
                      <div className="marker-label-flag" style={{ backgroundColor: beach.color }}>
                         <Flag size={14} fill="#0f172a" stroke="#0f172a" />
                      </div>
                    </div>
                 </Marker>
               ))}
             </MapGL>
          </div>
        ) : loading ? (
          <div className="loading-spinner">
            <div className="spinner">🌊</div>
            {wakingUp && <p className="wake-message">{wakeMessage}</p>}
            {wakingUp && <p className="wake-hint">First load after idle can take up to 60 seconds on Render.</p>}
          </div>
        ) : data ? (
          <>
            <div className="header mobile-header">
              <div className="header-row">
                <div className="header-main">
                  <div className="beach-meta beach-meta-compact">
                    <span className="meta-item"><Thermometer size={14} /> {data.weather?.temp_f ?? '--'}°F air</span>
                    <span className="meta-item"><Droplets size={14} /> {data.tides?.water_temp ?? '--'}°F water</span>
                    <span className="meta-item"><Navigation2 size={14} /> {data.weather?.wind_mph ?? '--'} mph {data.weather?.wind_dir ?? ''}</span>
                    {lastUpdated && <span className="meta-item meta-muted">Updated {lastUpdated} (Florida)</span>}
                  </div>
                  {data.tides?.water_temp_source && (
                    <p className="water-temp-source">Water temp: {data.tides.water_temp_source}</p>
                  )}
                </div>
                <div className="glass-flag" style={{ borderColor: data.outlook?.color }}>
                  <Flag size={20} color={data.outlook?.color} fill={data.outlook?.color} />
                </div>
              </div>
            </div>

            <div className="header desktop-only">
              <div className="header-row">
                <div className="header-main">
                  <h1 className="beach-name">{data.beach}</h1>
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
            </div>

            <div className="grid">
              <div className="card hero-card" style={{ borderLeft: `6px solid ${data.outlook?.verdict?.color ?? data.outlook?.color ?? '#3b82f6'}` }}>
                <div className="card-title"><Calendar size={18} /> {data.outlook?.verdict_title ?? "Today's outlook"}</div>
                <div className="card-value hero-value">{data.outlook?.verdict?.headline ?? data.outlook?.label ?? '--'}</div>
                <div className="card-subvalue reason-text">{data.outlook?.verdict?.reason ?? data.outlook?.reason ?? '--'}</div>

                <div className="outlook-split">
                  <div className="outlook-panel" style={{ borderColor: data.outlook?.water_now?.color ?? data.outlook?.color }}>
                    <span className="outlook-panel-label">Water now</span>
                    <span className="outlook-panel-value" style={{ color: data.outlook?.water_now?.color ?? data.outlook?.color }}>
                      {data.outlook?.water_now?.label ?? data.outlook?.label ?? '--'}
                    </span>
                    <span className="outlook-panel-meta">{data.outlook?.water_now?.summary ?? data.outlook?.reason}</span>
                    <span className="outlook-panel-note">Official beach flag</span>
                  </div>
                  <div className="outlook-panel" style={{ borderColor: data.outlook?.plan_today?.color ?? '#64748b' }}>
                    <span className="outlook-panel-label">{data.outlook?.plan_label ?? 'Plan for today'}</span>
                    <span className="outlook-panel-value" style={{ color: data.outlook?.plan_today?.color ?? '#94a3b8' }}>
                      {data.outlook?.plan_today?.status ?? '--'}
                    </span>
                    <span className="outlook-panel-meta">{data.outlook?.plan_today?.headline ?? '--'}</span>
                    {data.outlook?.plan_today?.forecast && (
                      <span className="outlook-panel-note">{data.outlook.plan_today.forecast}</span>
                    )}
                    {data.outlook?.plan_today?.hourly_lines && data.outlook.plan_today.hourly_lines.length > 0 ? (
                      <div className="hourly-forecast">
                        <span className="outlook-panel-note hourly-forecast-label">Next few hours</span>
                        <ul className="hourly-forecast-list">
                          {data.outlook.plan_today.hourly_lines.map((line, i) => (
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
                    ) : data.outlook?.plan_today?.hourly ? (
                      <span className="outlook-panel-note">Next few hours: {data.outlook.plan_today.hourly}</span>
                    ) : null}
                    {data.outlook?.radar_proximity?.storm_nearby && (
                      <span className="outlook-panel-note">
                        Radar: {data.outlook.radar_proximity.max_dbz} dBZ within {data.outlook.radar_proximity.radius_miles} mi
                      </span>
                    )}
                  </div>
                </div>

                {data.outlook?.active_alerts && data.outlook.active_alerts.length > 0 && (
                  <div className="active-alerts">
                    {data.outlook.active_alerts.map((alert, i) => (
                      <p key={i} className="active-alert-item">
                        <Zap size={14} />
                        <span><strong>{alert.event}:</strong> {alert.headline}</span>
                      </p>
                    ))}
                  </div>
                )}

                <div className="activity-status-line">
                   <div className="status-item">
                      <span className={`dot ${activityStatus(data.outlook?.activities, 'paddling')}`}></span> Paddling
                   </div>
                   <span className="divider-sm">|</span>
                   <div className="status-item">
                      <span className={`dot ${activityStatus(data.outlook?.activities, 'swimming')}`}></span> Swimming
                   </div>
                   <span className="divider-sm">|</span>
                   <div className="status-item">
                      <span className={`dot ${activityStatus(data.outlook?.activities, 'beach')}`}></span> Beach
                   </div>
                </div>
                {data.outlook?.activities_summary ? (
                  <p className="activity-note">{data.outlook.activities_summary}</p>
                ) : (
                  <div className="activity-reasons">
                    {(['paddling', 'swimming', 'beach'] as const).map(key => {
                      const reason = activityReason(data.outlook?.activities, key);
                      if (!reason || activityStatus(data.outlook?.activities, key) === 'Green') return null;
                      return (
                        <p key={key} className="activity-note">
                          <strong>{key.charAt(0).toUpperCase() + key.slice(1)}:</strong> {reason}
                        </p>
                      );
                    })}
                  </div>
                )}
              </div>

              {data.teeth && (
                <div className="card teeth-card">
                  <div className="card-title"><Footprints size={18} /> Shark Tooth Hunt</div>
                  <div className="card-value">{data.teeth.label} <span className="teeth-score">{data.teeth.score}/10</span></div>
                  <div className="card-subvalue reason-text">{data.teeth.tip}</div>
                  <div className="source-label">Fossil beaches: Venice, Manasota Key, Caspersen, Nokomis, Englewood</div>
                </div>
              )}

              {/* Weather & Forecast Card */}
              <div className="card forecast-card">
                <div className="card-title"><CloudSun size={18} /> Detailed Forecast</div>
                <div className="card-value forecast-text">{data.forecast?.summary ?? '--'}</div>
                <div className="source-label">Source: {data.forecast?.source ?? 'NWS'}</div>
              </div>

              <div className="card">
                <div className="card-title"><Waves size={18} /> Surf</div>
                <div className="card-value">{data.surf?.intensity ?? 'Unknown'}</div>
                <div className="card-subvalue">{data.surf?.type ?? '--'} | {data.surf?.height ?? '--'}ft | {data.surf?.period ?? '--'}s period</div>
                <div className="activity-list" style={{ marginTop: '12px' }}>
                   <div className="activity-item">
                      <AlertTriangle size={16} color={data.surf?.rip_current?.includes('High') ? '#f87171' : '#4ade80'} />
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

              <div className="card">
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

              <div className="card">
                <div className="card-title"><Moon size={18} /> Skywatch</div>
                <div className="card-value" style={{ fontSize: '1.5rem' }}>{data.skywatch?.moon_phase ?? '--'}</div>
                <div className="card-subvalue" style={{ color: '#3b82f6', fontWeight: 700 }}>{data.skywatch?.illumination ?? '--'} Illum.</div>
              </div>

              <div className="card">
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

              <div className="card">
                <div className="card-title"><AlertTriangle size={18} /> Red Tide</div>
                <div className="card-value" style={{ color: data.red_tide?.status !== 'Not Present' ? '#f87171' : '#4ade80' }}>
                  {data.red_tide?.status ?? '--'}
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

export default App;
