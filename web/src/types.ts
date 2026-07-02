export interface Beach {
  id: string;
  name: string;
  lat: number;
  lon: number;
  color?: string;
  storm_badge?: boolean;
  radar_nearby?: boolean;
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