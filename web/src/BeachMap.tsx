import 'mapbox-gl/dist/mapbox-gl.css';
import { Flag, Radar, Zap } from 'lucide-react';
import MapGL, { Layer, Marker, NavigationControl, Source } from 'react-map-gl/mapbox';
import type { Beach, MapFocus } from './types';

const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN || '';

export interface BeachMapProps {
  beaches: Beach[];
  selectedBeach: string;
  selectBeach: (id: string) => void;
  mapFocus: MapFocus;
  mapZoom: number;
  setMapZoom: (z: number) => void;
  showRadar: boolean;
  setShowRadar: (v: boolean) => void;
}

export default function BeachMap({
  beaches,
  selectedBeach,
  selectBeach,
  mapFocus,
  mapZoom,
  setMapZoom,
  showRadar,
  setShowRadar,
}: BeachMapProps) {
  return (
    <div className="map-container-fixed" style={{ position: 'relative' }}>
      <button
        className={`radar-toggle ${showRadar ? 'active' : ''}`}
        onClick={() => setShowRadar(!showRadar)}
        title="Toggle NWS Weather Radar"
        type="button"
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
  );
}