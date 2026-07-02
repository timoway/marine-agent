import { useMemo, useState } from 'react';
import { MapPin, ChevronRight } from 'lucide-react';
import { distanceMiles, getPosition, type Coords } from './geo';
import type { Beach } from './types';

// First-run sheet (docs/roadmap-ios-launch.md §3): one sheet, three stacked
// moments — value-framed location ask, distance-sorted beach picker, one-line
// verdict explainer. Skippable, never shown again.
export function OnboardingSheet({
  beaches,
  onPick,
  onSkip,
  onCoords,
}: {
  beaches: Beach[];
  onPick: (beachId: string) => void;
  onSkip: () => void;
  onCoords: (c: Coords) => void;
}) {
  const [coords, setCoords] = useState<Coords | null>(null);
  const [locating, setLocating] = useState(false);
  const [locError, setLocError] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);

  const sorted = useMemo(() => {
    if (coords) {
      return [...beaches]
        .map(b => ({ ...b, dist: distanceMiles(coords, { lat: b.lat, lon: b.lon }) }))
        .sort((a, b) => a.dist - b.dist);
    }
    return [...beaches].map(b => ({ ...b, dist: null as number | null }));
  }, [beaches, coords]);

  const locate = async () => {
    setLocating(true);
    setLocError(null);
    try {
      const c = await getPosition();
      setCoords(c);
      onCoords(c);
    } catch {
      setLocError("Couldn't get your location — pick a beach below instead.");
      setBrowsing(true);
    } finally {
      setLocating(false);
    }
  };

  const showList = coords !== null || browsing;
  const list = coords ? sorted.slice(0, 6) : sorted;

  return (
    <div className="pulse-sheet-overlay onboarding-overlay">
      <div className="pulse-sheet onboarding-sheet" role="dialog" aria-label="Welcome">
        <div className="pulse-sheet-header">
          <span>Is today a beach day?</span>
          <button className="pulse-signout onboarding-skip" onClick={onSkip}>Skip</button>
        </div>
        <p className="pulse-sheet-note">
          One clear answer for every Gulf beach — from NOAA, NWS, lifeguard flags, and
          people standing on the sand.
        </p>

        {!showList ? (
          <div className="onboarding-actions">
            <button className="onboarding-locate-btn" onClick={() => void locate()} disabled={locating}>
              <MapPin size={17} />
              {locating ? 'Finding your nearest beach…' : 'Find my nearest beach'}
            </button>
            <button className="onboarding-browse-btn" onClick={() => setBrowsing(true)}>
              Choose a beach myself
            </button>
          </div>
        ) : (
          <>
            {locError && <p className="pulse-sheet-message">{locError}</p>}
            <p className="account-section-title onboarding-list-title">
              {coords ? 'Closest to you' : 'Pick your beach'}
            </p>
            <div className="onboarding-beach-list">
              {list.map(b => (
                <button key={b.id} className="onboarding-beach-item" onClick={() => onPick(b.id)}>
                  <span className="beach-item-dot" style={{ backgroundColor: b.color }} />
                  <span className="onboarding-beach-name">{b.name}</span>
                  {b.dist != null && (
                    <span className="onboarding-beach-dist">{Math.round(b.dist)} mi</span>
                  )}
                  <ChevronRight size={15} className="beach-item-chevron" />
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
