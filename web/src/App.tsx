import { useState, useEffect, useMemo } from 'react';
import Map, { Marker, NavigationControl, Source, Layer } from 'react-map-gl/mapbox';
import 'mapbox-gl/dist/mapbox-gl.css';
import { 
  Waves, Thermometer, Eye, Droplets, AlertTriangle, 
  Ship, Calendar, Search, Menu, X, 
  Activity, Palette, Leaf, Moon, CloudSun, Navigation2,
  TrendingUp, TrendingDown, Flag, Radar
} from 'lucide-react';
import InstallPrompt from './InstallPrompt';
import { apiFetch } from './api';

// --- CONFIGURATION ---
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || '';
const REFRESH_MS = 5 * 60 * 1000; // match backend sync interval

interface Beach { id: string; name: string; lat: number; lon: number; color?: string; }

interface MarineData {
  beach: string;
  lat: number;
  lon: number;
  timestamp: string;
  tides: { predictions: any[]; water_temp: string; current_status: string; trend: string; next_event: string; source: string; };
  forecast: { summary: string; rip_current: string; source: string; };
  skywatch: { moon_phase: string; illumination: string; planets_visible: string; upcoming_event: string; };
  surf: { height: number; period: number; intensity: string; type: string; rip_current: string; };
  weather: { temp_f: number; wind_mph: number; wind_dir: string; };
  red_tide: { status: string; };
  mote_extras: { water: string; algae: string; algae_type: string; };
  outlook: { 
    label: string; 
    vibe: string; 
    reason: string; 
    color: string; 
    activities: { paddling: string; swimming: string; beach: string; };
  };
  teeth: { score: number; } | null;
  clarity: { label: string; feet: number; };
}

function App() {
  const [beaches, setBeaches] = useState<Beach[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBeach, setSelectedBeach] = useState<string>('venice');
  const [data, setData] = useState<MarineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [viewMode, setViewMode] = useState<'dashboard' | 'map'>('dashboard');
  const [showRadar, setShowRadar] = useState(false);

  useEffect(() => {
    const fetchBeaches = () => {
      apiFetch<Beach[]>('/beaches_with_flags')
        .then(setBeaches)
        .catch(err => console.error(err));
    };
    fetchBeaches();
    const interval = setInterval(fetchBeaches, REFRESH_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const fetchConditions = (showLoading: boolean) => {
      if (showLoading) {
        setLoading(true);
        setError(null);
      }
      apiFetch<MarineData>(`/conditions/${selectedBeach}`)
        .then(json => {
          if (cancelled) return;
          if ('error' in json && json.error) throw new Error(String(json.error));
          setData(json);
          setLoading(false);
          if (showLoading && window.innerWidth <= 1024) setSidebarOpen(false);
        })
        .catch(err => {
          if (cancelled) return;
          if (showLoading) {
            setError(err instanceof Error ? err.message : 'Failed to load beach data');
            setLoading(false);
          }
        });
    };

    fetchConditions(true);
    const interval = setInterval(() => fetchConditions(false), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedBeach]);

  const filteredBeaches = useMemo(() => beaches.filter(beach => 
    beach.name.toLowerCase().includes(searchQuery.toLowerCase())
  ), [beaches, searchQuery]);

  const lastUpdated = useMemo(() => {
    if (!data?.timestamp) return null;
    return new Date(data.timestamp).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  }, [data?.timestamp]);

  return (
    <div className="dashboard-container">
      <InstallPrompt />
      {sidebarOpen && window.innerWidth <= 1024 && (
        <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)}></div>
      )}

      {/* Sidebar */}
      <div className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
        <div className="sidebar-header">
           <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Ship color="white" size={24} />
              <h2 style={{ margin: 0, color: 'white', fontSize: '1.2rem' }}>MarineAgent</h2>
           </div>
           <button onClick={() => setSidebarOpen(false)} className="menu-close-mobile"><X size={24} /></button>
        </div>

        <div className="view-toggle">
           <button className={`toggle-btn ${viewMode === 'dashboard' ? 'active' : ''}`} onClick={() => setViewMode('dashboard')}>Dashboard</button>
           <button className={`toggle-btn ${viewMode === 'map' ? 'active' : ''}`} onClick={() => setViewMode('map')}>Map</button>
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
            <div 
              key={beach.id}
              className={`beach-item ${selectedBeach === beach.id ? 'active' : ''}`}
              onClick={() => { setSelectedBeach(beach.id); setViewMode('dashboard'); }}
            >
              <div className="beach-item-dot" style={{ backgroundColor: beach.color }}></div>
              {beach.name}
            </div>
          ))}
        </div>
      </div>

      <div className="main-content">
        {!sidebarOpen && (
          <button className="floating-menu-btn" onClick={() => setSidebarOpen(true)}>
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

             <Map
               initialViewState={{ latitude: 26.8, longitude: -82.35, zoom: 8.5 }}
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
                 <Marker key={beach.id} latitude={beach.lat} longitude={beach.lon} anchor="bottom" onClick={e => { e.originalEvent.stopPropagation(); setSelectedBeach(beach.id); setViewMode('dashboard'); }}>
                    <div className="map-marker-pulse">
                      <div className="pulse-ring" style={{ backgroundColor: `${beach.color}44` }}></div>
                      <div className="pulse-dot" style={{ backgroundColor: beach.color }}></div>
                      <div className="marker-label-flag" style={{ backgroundColor: beach.color }}>
                         <Flag size={14} fill="#0f172a" stroke="#0f172a" />
                         {/* <span className="label-text">{beach.name}</span> */}
                      </div>
                    </div>
                 </Marker>
               ))}
             </Map>
          </div>
        ) : loading ? (
          <div className="loading-spinner"><div className="spinner">🌊</div></div>
        ) : data ? (
          <>
            <div className="header desktop-only">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' }}>
                <div>
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
                        <span className="meta-item" style={{ opacity: 0.7 }}>Updated {lastUpdated}</span>
                      </>
                    )}
                  </div>
                </div>
                {/* GLASSY FLAG ICON */}
                <div className="glass-flag" style={{ borderColor: data.outlook?.color }}>
                   <Flag size={20} color={data.outlook?.color} fill={data.outlook?.color} />
                </div>
              </div>
            </div>

            <div className="grid">
              <div className="card hero-card" style={{ borderLeft: `6px solid ${data.outlook?.color ?? '#3b82f6'}` }}>
                <div className="card-title"><Calendar size={18} /> Daily Outlook</div>
                <div className="card-value hero-value">{data.outlook?.label ?? '--'}</div>
                <div className="card-subvalue reason-text">{data.outlook?.reason ?? '--'}</div>
                
                {/* ACTIVITY STATUS LINE */}
                <div className="activity-status-line">
                   <div className="status-item">
                      <span className={`dot ${data.outlook?.activities?.paddling}`}></span> Paddling
                   </div>
                   <span className="divider-sm">|</span>
                   <div className="status-item">
                      <span className={`dot ${data.outlook?.activities?.swimming}`}></span> Swimming
                   </div>
                   <span className="divider-sm">|</span>
                   <div className="status-item">
                      <span className={`dot ${data.outlook?.activities?.beach}`}></span> Beach
                   </div>
                </div>
              </div>

              {/* Weather & Forecast Card */}
              <div className="card" style={{ gridColumn: 'span 2' }}>
                <div className="card-title"><CloudSun size={18} /> Detailed Forecast</div>
                <div className="card-value" style={{ fontSize: '1.1rem', lineHeight: '1.6' }}>{data.forecast?.summary ?? '--'}</div>
                <div className="source-label">Source: {data.forecast?.source ?? 'NWS'}</div>
              </div>

              <div className="card">
                <div className="card-title"><Waves size={18} /> Surf</div>
                <div className="card-value">{data.surf?.intensity ?? 'Unknown'}</div>
                <div className="card-subvalue">{data.surf?.type ?? '--'} | {data.surf?.height ?? '--'}ft</div>
                <div className="activity-list" style={{ marginTop: '12px' }}>
                   <div className="activity-item">
                      <AlertTriangle size={16} color={data.surf?.rip_current?.includes('High') ? '#f87171' : '#4ade80'} />
                      <div style={{ fontSize: '0.9rem' }}><strong>Rip Currents:</strong> {data.surf?.rip_current ?? '--'}</div>
                   </div>
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
                <div className="card-title"><Droplets size={18} /> Upcoming Tides</div>
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
