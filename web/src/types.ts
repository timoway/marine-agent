export interface Beach {
  id: string;
  name: string;
  lat: number;
  lon: number;
  color?: string;
  storm_badge?: boolean;
  radar_nearby?: boolean;
}

// "Know before you go" — curated static facts, not live-fetched (Track 3).
export interface BeachAmenities {
  parking: 'free' | 'paid' | 'none' | 'unknown';
  parking_notes: string | null;
  dog_friendly: boolean;
  dog_notes: string | null;
  restrooms: boolean | null;
  lifeguard: 'year_round' | 'seasonal' | 'none' | 'unknown';
}

export interface MapFocus {
  longitude: number;
  latitude: number;
  zoom: number;
}

// --- Beach Pulse (community reports) ---
export type ReportType =
  | 'clarity' | 'crowd' | 'wildlife' | 'parking' | 'debris' | 'algae'
  | 'dead_fish' | 'surf' | 'jellyfish' | 'riptide' | 'shark' | 'red_tide';

export interface BeachPulseCount {
  type: ReportType;
  count: number;
  escalated: boolean;
  last_report_min_ago: number | null;
}

export interface BeachPulse {
  reports_enabled: boolean;
  total_today: number;
  counts: BeachPulseCount[];
}

export interface CommunityReport {
  id: string;
  report_type: ReportType;
  severity_tier: 'low' | 'moderate' | 'high';
  notes: string | null;
  status: 'published' | 'escalated';
  created_at: string;
}

// 'My reports' — the signed-in user's own reports across all beaches, any status.
export interface MyReport {
  id: string;
  beach_id: string;
  report_type: ReportType;
  severity_tier: 'low' | 'moderate' | 'high';
  notes: string | null;
  status: 'published' | 'escalated' | 'held_for_review';
  created_at: string;
}