import { useState } from 'react';
import { ParkingCircle, Dog, Bath, LifeBuoy, ChevronDown } from 'lucide-react';
import type { BeachAmenities } from './types';

const PARKING_LABEL: Record<BeachAmenities['parking'], string> = {
  free: 'Free parking',
  paid: 'Paid parking',
  none: 'No parking',
  unknown: 'Parking unknown',
};

const LIFEGUARD_LABEL: Record<BeachAmenities['lifeguard'], string> = {
  year_round: 'Lifeguard year-round',
  seasonal: 'Lifeguard seasonal',
  none: 'No lifeguard',
  unknown: 'Lifeguard unknown',
};

// "Know before you go" — one-sweep scannable facts under the beach header
// (docs/roadmap-ios-launch.md §7c). Tap a fact to expand its note, if any.
export function AmenitiesRow({ amenities }: { amenities?: BeachAmenities | null }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  if (!amenities) return null;

  const facts = [
    {
      key: 'parking',
      icon: <ParkingCircle size={15} />,
      label: PARKING_LABEL[amenities.parking],
      note: amenities.parking_notes,
    },
    {
      key: 'dog',
      icon: <Dog size={15} />,
      label: amenities.dog_friendly ? 'Dog-friendly' : 'No dogs',
      note: amenities.dog_notes,
      highlight: amenities.dog_friendly,
    },
    {
      key: 'restrooms',
      icon: <Bath size={15} />,
      label: amenities.restrooms == null ? 'Restrooms unknown' : amenities.restrooms ? 'Restrooms' : 'No restrooms',
      note: null as string | null,
    },
    {
      key: 'lifeguard',
      icon: <LifeBuoy size={15} />,
      label: LIFEGUARD_LABEL[amenities.lifeguard],
      note: null as string | null,
    },
  ];

  return (
    <div className="amenities-row">
      {facts.map(f => (
        <div key={f.key} className={`amenities-fact-wrap ${f.note ? 'has-note' : ''}`}>
          <button
            className={`amenities-fact ${f.highlight ? 'highlight' : ''}`}
            onClick={() => f.note && setExpanded(expanded === f.key ? null : f.key)}
            disabled={!f.note}
          >
            {f.icon}
            <span>{f.label}</span>
            {f.note && <ChevronDown size={12} className={`amenities-chevron ${expanded === f.key ? 'open' : ''}`} />}
          </button>
          {expanded === f.key && f.note && <p className="amenities-note">{f.note}</p>}
        </div>
      ))}
    </div>
  );
}
