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