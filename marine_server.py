import os
import datetime
import math
from io import BytesIO
import requests
from zoneinfo import ZoneInfo
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Tuple
from functools import lru_cache
from cachetools import TTLCache, cached
from PIL import Image
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn
from astral.moon import phase

print("[STARTUP] marine_server.py loading...")

# --- CONFIGURATION ---
FL_TZ = ZoneInfo("America/New_York")
OPENUV_KEY = os.environ.get("OPENUV_KEY", "")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "marine-secret-123")

def _fl_now() -> datetime.datetime:
    return datetime.datetime.now(FL_TZ)

# --- CACHING & PERFORMANCE ---
GLOBAL_DATA_STORE: Dict[str, dict] = {}

# --- DATA: STATIONS & BEACHES (SWFL + extended) ---
NOAA_STATIONS = {
    "8725889": {"name": "Venice (Roberts Bay)", "lat": 27.1000, "lon": -82.4433},
    "8726034": {"name": "Siesta Key, Big Sarasota Pass", "lat": 27.2839, "lon": -82.5650},
    "8726243": {"name": "Anna Maria Key, Bradenton Beach", "lat": 27.4967, "lon": -82.7133},
    "8726282": {"name": "Anna Maria Key, city pier", "lat": 27.5333, "lon": -82.7300},
    "8725577": {"name": "Port Boca Grande", "lat": 26.7267, "lon": -82.2583},
    "8725325": {"name": "Carlos Point (Fort Myers area)", "lat": 26.3983, "lon": -81.8767},
    "8725110": {"name": "Naples (Gulf of Mexico)", "lat": 26.1317, "lon": -81.8117},
    "8724967": {"name": "Marco Island (Caxambas Pass)", "lat": 25.9183, "lon": -81.7283},
    "8726724": {"name": "Clearwater Beach", "lat": 27.9783, "lon": -82.8317},
    "8726520": {"name": "St. Petersburg", "lat": 27.7717, "lon": -82.6283},
    "8729511": {"name": "Destin (East Pass)", "lat": 30.3800, "lon": -86.5133},
    "8729840": {"name": "Pensacola", "lat": 30.4033, "lon": -87.2117},
    "8729210": {"name": "Panama City Beach", "lat": 30.2133, "lon": -85.8783}
}

NWS_STATIONS = {
    "KVNC": {"name": "Venice Municipal Airport", "lat": 27.07, "lon": -82.44},
    "KSRQ": {"name": "Sarasota Bradenton Intl", "lat": 27.39, "lon": -82.55},
    "KPGD": {"name": "Punta Gorda Airport", "lat": 26.91, "lon": -81.99},
    "KFMY": {"name": "Page Field", "lat": 26.58, "lon": -81.86},
    "KAPF": {"name": "Naples Municipal Airport", "lat": 26.15, "lon": -81.77},
    "KMKY": {"name": "Marco Island Airport", "lat": 25.91, "lon": -81.67},
    "KPIE": {"name": "St. Pete-Clearwater Intl", "lat": 27.91, "lon": -82.68},
    "KSPG": {"name": "Albert Whitted Airport", "lat": 27.76, "lon": -82.62},
    "KDTS": {"name": "Destin Executive Airport", "lat": 30.39, "lon": -86.47},
    "KPNS": {"name": "Pensacola Intl", "lat": 30.47, "lon": -87.18},
    "KECP": {"name": "NW Florida Beaches Intl", "lat": 30.35, "lon": -85.79}
}

BEACH_CONFIG = {
    "venice": {"name": "Venice Beach", "mote_id": "33", "tide_id": "8725889", "county": "Sarasota", "lat": 27.1001, "lon": -82.4542, "nws_station": "KVNC", "shark_teeth": True},
    "manasota-key": {"name": "Manasota Key Beach", "mote_id": "6", "tide_id": "8725889", "county": "Sarasota", "lat": 27.0125, "lon": -82.4131, "nws_station": "KVNC", "shark_teeth": True},
    "siesta": {"name": "Siesta Key Beach", "mote_id": "2", "tide_id": "8726034", "county": "Sarasota", "lat": 27.2662, "lon": -82.5658, "nws_station": "KSRQ", "shark_teeth": False},
    "lido": {"name": "Lido Key Beach", "mote_id": "32", "tide_id": "8726034", "county": "Sarasota", "lat": 27.3188, "lon": -82.5786, "nws_station": "KSRQ", "shark_teeth": False},
    "caspersen": {"name": "Caspersen Beach", "mote_id": "34", "tide_id": "8725889", "county": "Sarasota", "lat": 27.0700, "lon": -82.4497, "nws_station": "KVNC", "shark_teeth": True},
    "nokomis": {"name": "Nokomis Beach", "mote_id": "35", "tide_id": "8725889", "county": "Sarasota", "lat": 27.1264, "lon": -82.4644, "nws_station": "KVNC", "shark_teeth": True},
    "englewood": {"name": "Englewood Beach", "mote_id": "7", "tide_id": "8725889", "county": "Charlotte", "lat": 26.9242, "lon": -82.3619, "nws_station": "KPGD", "shark_teeth": True},
    "fort-myers": {"name": "Fort Myers Beach", "mote_id": "145", "tide_id": "8725325", "county": "Lee", "lat": 26.4526, "lon": -81.9484, "nws_station": "KFMY", "shark_teeth": False},
    "bonita": {"name": "Bonita Beach", "mote_id": "144", "tide_id": "8725110", "county": "Lee", "lat": 26.3308, "lon": -81.8447, "nws_station": "KAPF", "shark_teeth": False},
    "vanderbilt": {"name": "Vanderbilt Beach", "mote_id": "114", "tide_id": "8725110", "county": "Collier", "lat": 26.2558, "lon": -81.8253, "nws_station": "KAPF", "shark_teeth": False},
    "barefoot": {"name": "Barefoot Beach", "mote_id": "144", "tide_id": "8725110", "county": "Collier", "lat": 26.3158, "lon": -81.8353, "nws_station": "KAPF", "shark_teeth": False},
    "bradenton": {"name": "Bradenton Beach", "mote_id": "4", "tide_id": "8726243", "county": "Manatee", "lat": 27.4695, "lon": -82.6987, "nws_station": "KSRQ", "shark_teeth": False},
    "anna-maria": {"name": "Anna Maria Island", "mote_id": "3", "tide_id": "8726282", "county": "Manatee", "lat": 27.5273, "lon": -82.7154, "nws_station": "KSRQ", "shark_teeth": False},
    "holmes": {"name": "Holmes Beach", "mote_id": "5", "tide_id": "8726243", "county": "Manatee", "lat": 27.4984, "lon": -82.7126, "nws_station": "KSRQ", "shark_teeth": False},
    "st-pete": {"name": "St. Pete Beach", "mote_id": "42", "tide_id": "8726520", "county": "Pinellas", "lat": 27.7253, "lon": -82.7412, "nws_station": "KSPG", "shark_teeth": False},
    "clearwater": {"name": "Clearwater Beach", "mote_id": "45", "tide_id": "8726724", "county": "Pinellas", "lat": 27.9781, "lon": -82.8317, "nws_station": "KPIE", "shark_teeth": False},
    "indian-rocks": {"name": "Indian Rocks Beach", "mote_id": "46", "tide_id": "8726724", "county": "Pinellas", "lat": 27.8931, "lon": -82.8482, "nws_station": "KPIE", "shark_teeth": False},
    "madeira": {"name": "Madeira Beach", "mote_id": "44", "tide_id": "8726520", "county": "Pinellas", "lat": 27.7945, "lon": -82.7840, "nws_station": "KSPG", "shark_teeth": False},
    "destin": {"name": "Destin", "mote_id": "100", "tide_id": "8729511", "county": "Okaloosa", "lat": 30.3935, "lon": -86.4958, "nws_station": "KDTS", "shark_teeth": False},
    "pensacola": {"name": "Pensacola Beach", "mote_id": "101", "tide_id": "8729840", "county": "Escambia", "lat": 30.3327, "lon": -87.1414, "nws_station": "KPNS", "shark_teeth": False},
    "panama-city": {"name": "Panama City Beach", "mote_id": "102", "tide_id": "8729210", "county": "Bay", "lat": 30.1766, "lon": -85.8055, "nws_station": "KECP", "shark_teeth": False}
}

# --- HELPERS ---
def distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 3958.8
    dlat, dlon = math.radians(lat1 - lat2), math.radians(lon1 - lon2)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat2)) * math.cos(math.radians(lat1)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def _format_time_12h(dt: datetime.datetime) -> str:
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {suffix}"

def calculate_relative_position(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    d = distance_miles(lat1, lon1, lat2, lon2)
    dlat, dlon = math.radians(lat1 - lat2), math.radians(lon1 - lon2)
    bearing = math.degrees(math.atan2(
        math.sin(dlon) * math.cos(math.radians(lat1)),
        math.cos(math.radians(lat2)) * math.sin(math.radians(lat1)) - math.sin(math.radians(lat2)) * math.cos(math.radians(lat1)) * math.cos(dlon),
    ))
    cardinal = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(bearing / 45) % 8]
    return f"{d:.1f} miles {cardinal}"

def calculate_flag(wave_ft: float, wind_mph: float, red_tide_status: str, jellyfish_detected: bool) -> dict:
    if red_tide_status == "Medium/High" or wave_ft > 6.0:
        return {"label": "DOUBLE RED", "vibe": "Water Closed", "color": "#7f1d1d"}
    if wave_ft > 4.0 or wind_mph > 25 or red_tide_status != "Not Present":
        return {"label": "RED FLAG", "vibe": "High Hazard", "color": "#f87171"}
    if jellyfish_detected:
        return {"label": "PURPLE FLAG", "vibe": "Stinging Life", "color": "#a855f7"}
    if wave_ft > 1.5 or wind_mph > 12:
        return {"label": "YELLOW FLAG", "vibe": "Medium Hazard", "color": "#facc15"}
    return {"label": "GREEN FLAG", "vibe": "Low Hazard", "color": "#4ade80"}

ACTIVITY_RANK = {"Green": 0, "Yellow": 1, "Red": 2}
VALID_ACTIVITIES = frozenset({"paddling", "swimming", "beach"})
VERDICT_COLORS = {"Green": "#4ade80", "Yellow": "#facc15", "Red": "#f87171"}
LIKELIHOOD_RANK = {"none": 0, "chance": 1, "likely": 2, "active": 3, "severe": 4}

RADAR_TILE_URL = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png"
RADAR_ZOOM = 8
RADAR_SAMPLE_RADIUS_MI = 12
RADAR_DBZ_MODERATE = 30
RADAR_DBZ_HEAVY = 40
_RADAR_TILE_CACHE: TTLCache = TTLCache(maxsize=96, ttl=90)

N0Q_DBZ_COLORS: List[Tuple[Tuple[int, int, int], int]] = [
    ((4, 233, 231), 5), ((1, 159, 244), 10), ((0, 219, 0), 15), ((0, 143, 0), 20),
    ((255, 255, 0), 25), ((231, 192, 0), 30), ((255, 144, 0), 35), ((255, 0, 0), 40),
    ((214, 0, 0), 45), ((192, 0, 0), 50), ((255, 0, 255), 55), ((153, 85, 201), 60),
    ((255, 255, 255), 65), ((179, 179, 179), 70),
]

def _lat_lon_to_tile_xy(lat: float, lon: float, zoom: int) -> Tuple[int, int, float, float]:
    n = 2 ** zoom
    x_frac = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y_frac = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return int(x_frac), int(y_frac), x_frac, y_frac

def _fetch_radar_tile(z: int, x: int, y: int) -> Optional[Image.Image]:
    key = (z, x, y)
    if key in _RADAR_TILE_CACHE:
        return _RADAR_TILE_CACHE[key]
    try:
        url = RADAR_TILE_URL.format(z=z, x=x, y=y)
        resp = requests.get(url, timeout=4)
        if not resp.ok:
            return None
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        _RADAR_TILE_CACHE[key] = img
        return img
    except Exception:
        return None

def _rgb_to_dbz(r: int, g: int, b: int, a: int) -> int:
    if a < 48 or (r + g + b) < 36:
        return 0
    best_dbz = 0
    best_dist = float("inf")
    for (cr, cg, cb), dbz in N0Q_DBZ_COLORS:
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_dbz = dbz
    return best_dbz if best_dist <= 9000 else 0

def _sample_dbz_at(lat: float, lon: float, zoom: int = RADAR_ZOOM) -> int:
    tile_x, tile_y, x_frac, y_frac = _lat_lon_to_tile_xy(lat, lon, zoom)
    img = _fetch_radar_tile(zoom, tile_x, tile_y)
    if img is None:
        return 0
    px = min(255, max(0, int((x_frac - tile_x) * 256)))
    py = min(255, max(0, int((y_frac - tile_y) * 256)))
    r, g, b, a = img.getpixel((px, py))
    return _rgb_to_dbz(r, g, b, a)

def _get_radar_proximity(lat: float, lon: float) -> dict:
    """Sample NWS NEXRAD mosaic near a beach. Complements point-based NWS alerts."""
    max_dbz = 0
    lat_deg_mi = 1.0 / 69.0
    lon_deg_mi = 1.0 / (69.0 * max(0.2, math.cos(math.radians(lat))))
    steps = (-1, 0, 1)
    for dlat in steps:
        for dlon in steps:
            sample_lat = lat + dlat * RADAR_SAMPLE_RADIUS_MI * lat_deg_mi
            sample_lon = lon + dlon * RADAR_SAMPLE_RADIUS_MI * lon_deg_mi
            max_dbz = max(max_dbz, _sample_dbz_at(sample_lat, sample_lon))
    level = "none"
    if max_dbz >= RADAR_DBZ_HEAVY:
        level = "heavy"
    elif max_dbz >= RADAR_DBZ_MODERATE:
        level = "moderate"
    return {
        "max_dbz": max_dbz,
        "level": level,
        "storm_nearby": level in ("moderate", "heavy"),
        "radius_miles": RADAR_SAMPLE_RADIUS_MI,
    }

def _max_status(*statuses: str) -> str:
    return max(statuses, key=lambda s: ACTIVITY_RANK.get(s, 2))

def _activity_status_value(activities: dict, activity: str) -> str:
    val = activities.get(activity, "Red")
    if isinstance(val, dict):
        return val.get("status", "Red")
    return val

def _storm_likelihood_in_text(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("hurricane warning", "tropical storm warning", "tornado warning")):
        return "severe"
    if any(k in t for k in ("severe thunderstorm warning", "flash flood warning")):
        return "active"
    if any(k in t for k in ("hurricane watch", "tropical storm watch")):
        return "likely"
    hedged = ("chance of", "possible", "isolated", "scattered", "slight chance", "may produce", "could see")
    storm_terms = ("thunderstorms", "thunderstorm", "storms and", "storms likely", "storms expected", "storms possible")
    has_storm = any(term in t for term in storm_terms) or ("showers" in t and "thunder" in t)
    if has_storm:
        if any(h in t for h in hedged):
            if any(s in t for s in ("likely", "expected", "definite", "numerous")):
                return "likely"
            return "chance"
        return "active"
    if "rain" in t or "showers" in t:
        if any(h in t for h in hedged):
            return "chance"
        return "likely"
    return "none"

def _max_likelihood(*levels: str) -> str:
    return max(levels, key=lambda lvl: LIKELIHOOD_RANK.get(lvl, 0))

def _empty_hazards() -> dict:
    return {
        "hurricane_warning": False,
        "hurricane_watch": False,
        "tropical_storm_warning": False,
        "tropical_storm_watch": False,
        "severe_thunderstorm_warning": False,
        "tornado_warning": False,
        "special_marine_warning": False,
        "special_weather_statement": False,
        "marine_weather_statement": False,
    }

def _pop_to_likelihood(pop: Optional[int], short_forecast: str) -> str:
    sf = (short_forecast or "").lower()
    text_lvl = _storm_likelihood_in_text(sf)
    if pop is None:
        return text_lvl
    if pop >= 70:
        return _max_likelihood(text_lvl, "likely")
    if pop >= 50:
        return _max_likelihood(text_lvl, "chance")
    return text_lvl

def _analyze_hourly(hourly_periods: list) -> dict:
    now = _fl_now()
    current = None
    next_hours = []
    for period in hourly_periods[:8]:
        try:
            start = datetime.datetime.fromisoformat(period["startTime"])
        except (KeyError, ValueError, TypeError):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=FL_TZ)
        delta_h = (start - now).total_seconds() / 3600
        if -1 <= delta_h < 1 and current is None:
            current = period
        elif 0 <= delta_h < 3:
            next_hours.append(period)

    window = ([current] if current else []) + next_hours
    if not window and hourly_periods:
        window = hourly_periods[:3]

    max_pop = 0
    now_likelihood = "none"
    summaries = []
    for period in window:
        pop = period.get("probabilityOfPrecipitation", {}).get("value")
        if pop is not None:
            max_pop = max(max_pop, int(pop))
        short_fc = period.get("shortForecast", "")
        summaries.append(f"{period.get('startTime', '')[:16]}: {short_fc} ({pop or 0}% PoP)")
        lvl = _pop_to_likelihood(pop, short_fc)
        if period is current or period in next_hours[:2]:
            now_likelihood = _max_likelihood(now_likelihood, lvl)

    return {
        "now_likelihood": now_likelihood,
        "max_pop": max_pop,
        "current_short": current.get("shortForecast", "") if current else "",
        "summary": "; ".join(summaries[:3]),
    }

def _analyze_weather_situation(forecast: dict) -> dict:
    now = _fl_now()
    hour = now.hour
    periods = forecast.get("periods", [])
    hazards = forecast.get("hazards", {})
    active_alerts = forecast.get("active_alerts", [])

    if hazards.get("hurricane_warning") or hazards.get("tropical_storm_warning") or hazards.get("tornado_warning"):
        advisory_level = "severe"
        advisory_reason = "Active NWS warning for tropical or severe weather"
    elif hazards.get("special_marine_warning") or hazards.get("severe_thunderstorm_warning"):
        advisory_level = "active"
        advisory_reason = next(
            (a["headline"] for a in active_alerts if a["event"] in ("Special Marine Warning", "Severe Thunderstorm Warning")),
            "Active marine or severe thunderstorm warning",
        )
    elif hazards.get("special_weather_statement"):
        advisory_level = "active"
        advisory_reason = next(
            (a["headline"] for a in active_alerts if a["event"] == "Special Weather Statement"),
            "NWS special weather statement for nearby storms",
        )
    elif hazards.get("marine_weather_statement"):
        advisory_level = "likely"
        advisory_reason = next(
            (a["headline"] for a in active_alerts if a["event"] == "Marine Weather Statement"),
            "Marine weather statement in effect",
        )
    elif hazards.get("hurricane_watch") or hazards.get("tropical_storm_watch"):
        advisory_level = "likely"
        advisory_reason = "Tropical weather watch in effect"
    else:
        advisory_level = "none"
        advisory_reason = ""

    current_text = ""
    later_text = ""
    for i, period in enumerate(periods[:4]):
        name = period.get("name", "").lower()
        text = period.get("detailedForecast", "")
        full = f"{name} {text}"
        if "afternoon" in name:
            if hour < 12:
                later_text += f" {full}"
            else:
                current_text += f" {full}"
        elif "morning" in name or name == "today":
            if hour < 12:
                current_text += f" {full}"
            else:
                later_text += f" {full}"
        elif "tonight" in name or "evening" in name:
            later_text += f" {full}"
        elif i == 0:
            if hour < 12 and "afternoon" in text.lower():
                current_text += f" {name}"
                later_text += f" {text}"
            else:
                current_text += f" {full}"

    if not current_text.strip() and periods:
        current_text = periods[0].get("detailedForecast", "")
    if not later_text.strip() and len(periods) > 1:
        later_text = periods[1].get("detailedForecast", "")

    summary = forecast.get("summary", "")
    now_likelihood = _max_likelihood(_storm_likelihood_in_text(current_text))
    later_likelihood = _max_likelihood(_storm_likelihood_in_text(later_text))
    if hour < 12:
        later_likelihood = _max_likelihood(later_likelihood, _storm_likelihood_in_text(summary))
    else:
        now_likelihood = _max_likelihood(now_likelihood, _storm_likelihood_in_text(summary))

    hourly = _analyze_hourly(forecast.get("hourly_periods", []))
    if hourly["now_likelihood"] != "none":
        now_likelihood = _max_likelihood(now_likelihood, hourly["now_likelihood"])
    if hourly["max_pop"] >= 70:
        now_likelihood = _max_likelihood(now_likelihood, "likely")
    elif hourly["max_pop"] >= 50:
        now_likelihood = _max_likelihood(now_likelihood, "chance")

    radar_proximity = forecast.get("radar_proximity", {})
    if radar_proximity.get("storm_nearby") and advisory_level == "none":
        if radar_proximity.get("level") == "heavy":
            now_likelihood = _max_likelihood(now_likelihood, "likely")
        elif radar_proximity.get("level") == "moderate":
            now_likelihood = _max_likelihood(now_likelihood, "chance")

    return {
        "hour": hour,
        "advisory_level": advisory_level,
        "advisory_reason": advisory_reason,
        "now_likelihood": now_likelihood,
        "later_likelihood": later_likelihood,
        "forecast_headline": summary,
        "hourly_summary": hourly.get("summary", ""),
        "hourly_max_pop": hourly.get("max_pop", 0),
        "current_period": periods[0].get("name", "") if periods else "",
        "active_alerts": active_alerts,
        "radar_proximity": radar_proximity,
    }

def _radar_plan_reason(situation: dict) -> Optional[str]:
    radar = situation.get("radar_proximity", {})
    if not radar.get("storm_nearby") or situation.get("advisory_level") != "none":
        return None
    dbz = radar.get("max_dbz", 0)
    if radar.get("level") == "heavy":
        return f"Heavy precipitation on radar nearby ({dbz} dBZ)"
    if radar.get("level") == "moderate":
        return f"Precipitation detected on radar nearby ({dbz} dBZ)"
    return None

def _forecast_plan_status(situation: dict) -> tuple[str, str]:
    advisory = situation["advisory_level"]
    if advisory in ("severe", "active"):
        return "Red", situation["advisory_reason"] or "Active weather advisory"
    if advisory == "likely":
        return "Red", situation["advisory_reason"] or "Tropical weather threat"

    radar_reason = _radar_plan_reason(situation)
    if radar_reason:
        return "Yellow", radar_reason

    now_lvl = situation["now_likelihood"]
    later_lvl = situation["later_likelihood"]
    hour = situation["hour"]

    if now_lvl in ("severe", "active"):
        return "Red", "Storms active or imminent right now"
    if now_lvl == "likely":
        return "Red", "Storms likely in the current period"

    if hour < 12:
        if later_lvl == "likely":
            return "Yellow", "Storms likely this afternoon — best window is this morning"
        if later_lvl == "chance":
            return "Green", "Good conditions now — storms possible this afternoon"
        if later_lvl == "active":
            return "Yellow", "Storm risk building toward afternoon"
        return "Green", "Favorable conditions expected today"

    if now_lvl == "likely":
        return "Yellow", "Storms likely this afternoon"
    if now_lvl == "chance":
        return "Yellow", "Storms possible this afternoon"
    if later_lvl in ("likely", "active"):
        return "Yellow", "Storms possible later today"
    if later_lvl == "chance":
        return "Yellow", "Isolated storms possible later"
    return "Green", "Conditions look favorable for the rest of today"

def _physical_activity_status(activity: str, wave_ft: float, wind_mph: float, red_tide: str) -> tuple[str, str]:
    if activity == "paddling":
        if wind_mph > 15 or wave_ft > 2.5:
            return "Red", f"High wind ({wind_mph} mph) or surf ({wave_ft:.1f} ft)"
        if wind_mph > 10:
            return "Yellow", f"Moderate wind ({wind_mph} mph)"
        return "Green", f"Calm wind ({wind_mph} mph) and light surf ({wave_ft:.1f} ft)"
    if activity == "swimming":
        if wave_ft > 3.0 or red_tide != "Not Present":
            reason = "Red tide present" if red_tide != "Not Present" else f"High surf ({wave_ft:.1f} ft)"
            return "Red", reason
        if wave_ft > 1.5:
            return "Yellow", f"Moderate surf ({wave_ft:.1f} ft)"
        return "Green", f"Light surf ({wave_ft:.1f} ft)"
    if wave_ft > 4.0 or wind_mph > 22:
        return "Yellow", f"Windy or rough surf ({wind_mph} mph, {wave_ft:.1f} ft)"
    return "Green", "Comfortable beach conditions"

def _forecast_activity_status(activity: str, situation: dict) -> tuple[str, str]:
    advisory = situation["advisory_level"]
    if advisory in ("severe", "active", "likely"):
        return "Red", situation["advisory_reason"] or "Weather advisory in effect"

    radar_reason = _radar_plan_reason(situation)
    if radar_reason:
        return "Yellow", radar_reason

    now_lvl = situation["now_likelihood"]
    later_lvl = situation["later_likelihood"]
    hour = situation["hour"]

    if now_lvl in ("severe", "active", "likely"):
        return "Red", "Storms in the current period"

    if hour < 12:
        if later_lvl == "likely":
            return "Yellow", "Storms likely this afternoon"
        if later_lvl == "chance":
            return "Green", "Morning window before possible afternoon storms"
        return "Green", "No significant storm risk forecast"

    if now_lvl == "likely":
        return "Yellow", "Storms likely this afternoon"
    if now_lvl == "chance":
        return "Yellow", "Storms possible this afternoon"
    if later_lvl in ("likely", "active"):
        return "Yellow", "Storms possible later today"
    if later_lvl == "chance":
        return "Yellow", "Isolated storms possible later"
    return "Green", "No significant storm risk forecast"

def _build_activities(situation: dict, wave_ft: float, wind_mph: float, red_tide: str) -> dict:
    activities = {}
    for name in VALID_ACTIVITIES:
        phys_status, phys_reason = _physical_activity_status(name, wave_ft, wind_mph, red_tide)
        fc_status, fc_reason = _forecast_activity_status(name, situation)
        status = _max_status(phys_status, fc_status)
        if status == phys_status and phys_status != "Green":
            reason = phys_reason
        elif status == fc_status and fc_status != "Green":
            reason = fc_reason
        elif status == "Green":
            reason = phys_reason if phys_status == "Green" else fc_reason
        else:
            reason = fc_reason if fc_status != "Green" else phys_reason
        activities[name] = {"status": status, "reason": reason}
    return activities

def _activities_summary(activities: dict) -> Optional[str]:
    reasons = {a["reason"] for a in activities.values() if a["status"] != "Green"}
    if len(reasons) == 1:
        return reasons.pop()
    statuses = {a["status"] for a in activities.values()}
    if statuses == {"Green"}:
        return "All activities look good right now"
    return None

def _compute_verdict(flag: dict, plan_status: str, plan_reason: str, situation: dict, wave_ft: float, wind_mph: float) -> dict:
    if flag["label"] == "DOUBLE RED":
        headline, status = "Avoid — water closed", "Red"
        reason = "Dangerous surf or severe biological hazard"
    elif situation["advisory_level"] == "severe":
        headline, status = "Avoid — severe weather advisory", "Red"
        reason = situation["advisory_reason"]
    elif flag["label"] == "RED FLAG":
        headline, status = "High hazard — stay out of the water", "Red"
        reason = f"Official red flag conditions ({wave_ft:.1f} ft surf, {wind_mph} mph wind)"
    elif situation["advisory_level"] in ("active", "likely"):
        headline, status = "Not recommended — weather advisory", "Red"
        reason = situation["advisory_reason"]
    elif plan_status == "Red":
        headline, status = "Not recommended right now", "Red"
        reason = plan_reason
    elif plan_status == "Yellow":
        headline = "Go with caution"
        status = "Yellow"
        reason = plan_reason
    elif flag["label"] == "PURPLE FLAG":
        headline, status = "Caution — stinging marine life", "Yellow"
        reason = "Purple flag conditions — check Mote report"
    elif flag["label"] == "YELLOW FLAG":
        headline, status = "Okay with caution", "Yellow"
        reason = f"Moderate surf or wind ({wave_ft:.1f} ft, {wind_mph} mph). {plan_reason}"
    else:
        headline, status = "Good to go", "Green"
        reason = plan_reason

    return {
        "headline": headline,
        "status": status,
        "color": VERDICT_COLORS[status],
        "reason": reason,
    }

def _build_outlook(flag: dict, wave_ft: float, wind_mph: float, red_tide: str, mote: dict, forecast: dict) -> dict:
    situation = _analyze_weather_situation(forecast)
    plan_status, plan_reason = _forecast_plan_status(situation)
    activities = _build_activities(situation, wave_ft, wind_mph, red_tide)
    verdict = _compute_verdict(flag, plan_status, plan_reason, situation, wave_ft, wind_mph)
    official_reason = _get_daily_outlook(wave_ft, wind_mph, red_tide, mote, forecast)["reason"]

    return {
        **flag,
        "reason": official_reason,
        "water_now": {
            "label": flag["label"],
            "vibe": flag["vibe"],
            "color": flag["color"],
            "summary": f"{wave_ft:.1f} ft surf · {wind_mph} mph wind",
        },
        "plan_today": {
            "status": plan_status,
            "color": VERDICT_COLORS[plan_status],
            "headline": plan_reason,
            "forecast": situation["forecast_headline"],
            "hourly": situation.get("hourly_summary", ""),
        },
        "verdict": verdict,
        "activities": activities,
        "activities_summary": _activities_summary(activities),
        "storm_badge": len(situation.get("active_alerts", [])) > 0,
        "radar_nearby": situation.get("radar_proximity", {}).get("storm_nearby", False),
        "radar_proximity": situation.get("radar_proximity", {}),
        "active_alerts": situation.get("active_alerts", []),
    }

def _has_red_tide(data: dict) -> bool:
    return data.get("red_tide", {}).get("status", "Not Present") != "Not Present"

def _has_purple_hazard(data: dict) -> bool:
    outlook = data.get("outlook", {})
    if outlook.get("label") == "PURPLE FLAG":
        return True
    jellyfish = str(data.get("mote_extras", {}).get("jellyfish", "None")).lower()
    return jellyfish not in ("none", "n/a", "")

def _rank_tier_level(data: dict) -> int:
    """Lower level = better rank. 4=avoid, 3=NWS warning, 2=caution, 1=radar, 0=best."""
    if _has_red_tide(data):
        return 4
    outlook = data.get("outlook", {})
    if outlook.get("storm_badge"):
        return 3
    if _has_purple_hazard(data):
        return 2
    radar = outlook.get("radar_proximity", {})
    if radar.get("level") == "heavy":
        return 2
    if outlook.get("radar_nearby"):
        return 1
    return 0

def _rank_tier(data: dict) -> str:
    level = _rank_tier_level(data)
    if level >= 4:
        return "avoid"
    if level >= 3:
        return "warning"
    if level >= 2:
        return "caution"
    if level >= 1:
        return "radar"
    return "best"

def _rank_sort_key(data: dict, activity: str) -> tuple:
    """Lower tuple = better rank."""
    outlook = data.get("outlook", {})
    tier_level = _rank_tier_level(data)
    verdict_status = outlook.get("verdict", {}).get("status")
    activity_status = _activity_status_value(outlook.get("activities", {}), activity)
    status_score = ACTIVITY_RANK.get(verdict_status or activity_status, 2)
    wind = data.get("weather", {}).get("wind_mph", 99)
    surf = data.get("surf", {}).get("height", 99)
    radar_dbz = outlook.get("radar_proximity", {}).get("max_dbz", 0)
    return (tier_level, status_score, wind, surf, -radar_dbz)

def _rank_summary(data: dict, activity: str) -> str:
    parts = [
        f"{activity.title()}: {_activity_status_value(data.get('outlook', {}).get('activities', {}), activity)}",
        f"{data.get('weather', {}).get('wind_mph', '--')} mph wind",
        f"{data.get('surf', {}).get('height', '--')} ft surf",
    ]
    red_tide = data.get("red_tide", {}).get("status", "Not Present")
    if red_tide != "Not Present":
        parts.append(f"red tide ({red_tide})")
    if _has_purple_hazard(data):
        parts.append("purple flag / stinging life")
    outlook = data.get("outlook", {})
    if outlook.get("storm_badge"):
        parts.append("NWS weather warning")
    elif outlook.get("radar_nearby"):
        parts.append(f"radar {outlook.get('radar_proximity', {}).get('max_dbz', 0)} dBZ nearby")
    return "; ".join(parts)

DEFAULT_NEARBY_RADIUS_MILES = 50
FALLBACK_NEARBY_RADIUS_MILES = 75

def _resolve_rank_anchor(
    beach_id: Optional[str] = None,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
) -> Optional[dict]:
    if beach_id and beach_id in BEACH_CONFIG:
        config = BEACH_CONFIG[beach_id]
        return {
            "beach_id": beach_id,
            "name": config["name"],
            "lat": config["lat"],
            "lon": config["lon"],
        }
    if near_lat is not None and near_lon is not None:
        return {"beach_id": None, "name": "Custom location", "lat": near_lat, "lon": near_lon}
    return None

def rank_beaches_data(
    activity: str = "paddling",
    limit: int = 5,
    beach_id: Optional[str] = None,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    radius_miles: Optional[float] = None,
) -> dict:
    activity = activity if activity in VALID_ACTIVITIES else "paddling"
    limit = max(1, min(limit, len(BEACH_CONFIG)))
    anchor = _resolve_rank_anchor(beach_id=beach_id, near_lat=near_lat, near_lon=near_lon)
    use_nearby = anchor is not None
    requested_radius = radius_miles if radius_miles is not None else DEFAULT_NEARBY_RADIUS_MILES
    active_radius = requested_radius if use_nearby else None
    radius_expanded = False

    candidates = []
    for candidate_id, config in BEACH_CONFIG.items():
        data = GLOBAL_DATA_STORE.get(candidate_id)
        if not data or data.get("error"):
            continue
        dist = None
        if use_nearby:
            dist = distance_miles(anchor["lat"], anchor["lon"], config["lat"], config["lon"])
            if dist > (active_radius or requested_radius):
                continue
        candidates.append((candidate_id, config, data, dist))

    if use_nearby and not candidates and requested_radius < FALLBACK_NEARBY_RADIUS_MILES:
        active_radius = FALLBACK_NEARBY_RADIUS_MILES
        radius_expanded = True
        for candidate_id, config in BEACH_CONFIG.items():
            data = GLOBAL_DATA_STORE.get(candidate_id)
            if not data or data.get("error"):
                continue
            dist = distance_miles(anchor["lat"], anchor["lon"], config["lat"], config["lon"])
            if dist <= active_radius:
                candidates.append((candidate_id, config, data, dist))

    candidates.sort(key=lambda item: _rank_sort_key(item[2], activity))
    results = []
    for idx, (candidate_id, config, data, dist) in enumerate(candidates[:limit], start=1):
        entry = {
            "rank": idx,
            "beach_id": candidate_id,
            "name": config["name"],
            "rank_tier": _rank_tier(data),
            "activity_status": _activity_status_value(data.get("outlook", {}).get("activities", {}), activity),
            "flag": data.get("outlook", {}).get("label", "UNKNOWN"),
            "wind_mph": data.get("weather", {}).get("wind_mph"),
            "surf_ft": data.get("surf", {}).get("height"),
            "red_tide": data.get("red_tide", {}).get("status", "Not Present"),
            "jellyfish": data.get("mote_extras", {}).get("jellyfish", "None"),
            "summary": _rank_summary(data, activity),
        }
        if dist is not None:
            entry["distance_miles"] = round(dist, 1)
        results.append(entry)

    response = {
        "activity": activity,
        "when": "today",
        "generated_at": _fl_now().isoformat(),
        "timezone": "America/New_York",
        "total_beaches": len(BEACH_CONFIG),
        "candidate_count": len(candidates),
        "ranked_count": len(results),
        "results": results,
    }
    if use_nearby and anchor:
        response["nearby"] = {
            "anchor_beach_id": anchor["beach_id"],
            "anchor_name": anchor["name"],
            "lat": anchor["lat"],
            "lon": anchor["lon"],
            "radius_miles": active_radius or requested_radius,
            "radius_expanded": radius_expanded,
        }
    return response

def get_beach_key(beach_name: str) -> Optional[str]:
    if not beach_name:
        return "venice"
    beach_name = beach_name.lower().replace(" ", "-")
    for key in BEACH_CONFIG:
        if key in beach_name:
            return key
    return None

# --- FETCHERS (public APIs, resilient) ---
def _get_mote_report(config: dict) -> dict:
    try:
        url = f"https://visitbeaches.org/api/reports?locationId={config['mote_id']}&latest=true"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5).json()
        if isinstance(r, list) and len(r) > 0:
            report = r[0]
            return {
                "intensity": report.get("surfIntensity", "Light"),
                "type": report.get("surfType", "Wind Swell"),
                "water": "Clear Water" if report.get("waterColor") == "Clear" else report.get("waterColor", "Greenish Blue"),
                "algae": "No Algae Observed" if report.get("driftAlgae") == "None" else "Algae Present",
                "algae_type": report.get("driftAlgaeType", "N/A"),
                "jellyfish": report.get("jellyfish", "None")
            }
    except Exception:
        pass
    return {"intensity": "Light", "type": "Wind Swell", "water": "Clear Water", "algae": "No Algae Observed", "algae_type": "N/A", "jellyfish": "None"}

def _get_red_tide_status(config: dict) -> str:
    try:
        url = "https://atoll.floridamarine.org/arcgis/rest/services/Projects_FWC/HAB_Current/FeatureServer/0/query"
        params = {"where": f"County = '{config['county']}'", "outFields": "Count_", "orderByFields": "SampleDate DESC", "resultRecordCount": 1, "f": "json"}
        r = requests.get(url, params=params, timeout=8).json()
        feat = r.get('features', [])
        if feat:
            cnt = feat[0]['attributes']['Count_']
            if cnt > 100000:
                return "Medium/High"
            elif cnt > 10000:
                return "Low"
    except Exception:
        pass
    return "Not Present"

def _get_marine_data(config: dict):
    try:
        url = (
            f"https://marine-api.open-meteo.com/v1/marine?latitude={config['lat']}&longitude={config['lon']}"
            "&hourly=wave_height,swell_wave_period,sea_surface_temperature&timezone=auto"
        )
        r = requests.get(url, timeout=5).json()
        h = _fl_now().hour
        wave_ft = r['hourly']['wave_height'][h] * 3.28
        period = r['hourly']['swell_wave_period'][h]
        sst_c = r['hourly']['sea_surface_temperature'][h]
        sst_f = round((sst_c * 9 / 5) + 32, 1) if sst_c is not None else None
        return wave_ft, period, sst_f
    except Exception:
        return 0.5, 4.0, None

def _get_nws_obs(config: dict):
    try:
        url = f"https://api.weather.gov/stations/{config['nws_station']}/observations/latest"
        r = requests.get(url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=5).json()
        p = r.get('properties', {})
        raw_temp = p.get('temperature', {}).get('value')
        temp_f = round((raw_temp * 9/5) + 32, 1) if raw_temp is not None else 75.0
        raw_wind = p.get('windSpeed', {}).get('value')
        wind_mph = round(raw_wind / 1.6, 1) if raw_wind is not None else 8.0
        wind_deg = p.get('windDirection', {}).get('value', 0)
        wind_dir = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round((wind_deg or 0) / 45) % 8]
        return temp_f, wind_mph, wind_dir
    except Exception:
        return 75.0, 8.0, "N/A"

STORM_ALERT_EVENTS = frozenset({
    "Special Marine Warning",
    "Marine Weather Statement",
    "Special Weather Statement",
    "Severe Thunderstorm Warning",
    "Tornado Warning",
    "Hurricane Warning",
    "Hurricane Watch",
    "Tropical Storm Warning",
    "Tropical Storm Watch",
    "Flash Flood Warning",
})

def _get_nws_forecast(config: dict):
    try:
        points_url = f"https://api.weather.gov/points/{config['lat']},{config['lon']}"
        points_r = requests.get(points_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        props = points_r['properties']
        f_url = props['forecast']
        f_r = requests.get(f_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        periods = f_r['properties']['periods']
        summary = f"{periods[0]['name']}: {periods[0]['detailedForecast']}"

        hourly_periods = []
        hourly_url = props.get('forecastHourly')
        if hourly_url:
            try:
                h_r = requests.get(hourly_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
                hourly_periods = h_r.get('properties', {}).get('periods', [])[:8]
            except Exception:
                pass

        alerts_url = f"https://api.weather.gov/alerts/active?point={config['lat']},{config['lon']}"
        a_r = requests.get(alerts_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        rip = "Low Risk"
        hazards = _empty_hazards()
        active_alerts = []
        for alert in a_r.get('features', []):
            aprops = alert.get('properties', {})
            headline = aprops.get('headline', '')
            event = aprops.get('event', '')
            combined = f"{headline} {event}".lower()
            if "rip current" in combined:
                rip = "High Risk (NWS Alert)"
            if event in STORM_ALERT_EVENTS:
                active_alerts.append({
                    "event": event,
                    "headline": headline,
                    "severity": aprops.get('severity', ''),
                    "urgency": aprops.get('urgency', ''),
                })
            if "hurricane warning" in combined:
                hazards["hurricane_warning"] = True
            elif "hurricane watch" in combined:
                hazards["hurricane_watch"] = True
            if "tropical storm warning" in combined:
                hazards["tropical_storm_warning"] = True
            elif "tropical storm watch" in combined:
                hazards["tropical_storm_watch"] = True
            if "severe thunderstorm warning" in combined:
                hazards["severe_thunderstorm_warning"] = True
            if "tornado warning" in combined:
                hazards["tornado_warning"] = True
            if event == "Special Marine Warning":
                hazards["special_marine_warning"] = True
            elif event == "Special Weather Statement":
                hazards["special_weather_statement"] = True
            elif event == "Marine Weather Statement":
                hazards["marine_weather_statement"] = True

        station_info = NWS_STATIONS.get(config['nws_station'], {"lat": config['lat'], "lon": config['lon']})
        dist = calculate_relative_position(station_info["lat"], station_info["lon"], config["lat"], config["lon"])
        return {
            "summary": summary,
            "rip_current": rip,
            "source": f"NWS {config['nws_station']} ({dist})",
            "periods": periods,
            "hourly_periods": hourly_periods,
            "hazards": hazards,
            "active_alerts": active_alerts,
        }
    except Exception:
        return {
            "summary": "Forecast intermittent.",
            "rip_current": "Low Risk",
            "source": "NWS",
            "periods": [],
            "hourly_periods": [],
            "hazards": _empty_hazards(),
            "active_alerts": [],
        }

def _get_water_temp(config: dict, modeled_sst_f: Optional[float]) -> tuple[str, str]:
    try:
        temp_url = (
            f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=latest&station={config['tide_id']}"
            "&product=water_temperature&datum=MLLW&time_zone=lst_ldt&units=english&format=json"
        )
        payload = requests.get(temp_url, timeout=3).json()
        if payload.get("data"):
            return payload["data"][0]["v"], "NOAA in-situ sensor"
    except Exception:
        pass
    if modeled_sst_f is not None:
        return str(modeled_sst_f), "Open-Meteo modeled nearshore"
    return "--", "Unavailable"

def _fetch_noaa_tide_predictions(station_id: str, begin_date: str, range_hours: int = 48) -> list:
    url = (
        f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?begin_date={begin_date}"
        f"&range={range_hours}&station={station_id}&product=predictions&datum=MLLW"
        "&time_zone=lst_ldt&interval=hilo&units=english&format=json"
    )
    last_err = None
    for attempt in range(3):
        try:
            payload = requests.get(url, timeout=12).json()
            if payload.get("error"):
                last_err = payload["error"]
                break
            preds = payload.get("predictions", [])
            if preds:
                return preds
            last_err = "empty predictions"
        except Exception as e:
            last_err = e
            if attempt < 2:
                continue
    if last_err:
        print(f"[WARN] NOAA tides {station_id}: {last_err}")
    return []

def _get_tide_data(config: dict, modeled_sst_f: Optional[float] = None):
    water_temp, water_temp_source = _get_water_temp(config, modeled_sst_f)
    station_info = NOAA_STATIONS.get(config['tide_id'], {"lat": config['lat'], "lon": config['lon']})
    dist = calculate_relative_position(station_info["lat"], station_info["lon"], config["lat"], config["lon"])
    fallback = {
        "predictions": [],
        "water_temp": water_temp,
        "water_temp_source": water_temp_source,
        "current_status": "N/A",
        "trend": "N/A",
        "next_event": "Tides Unavailable",
        "source": f"NOAA {config['tide_id']} ({dist})",
    }
    try:
        now = _fl_now()
        begin = now.strftime("%Y%m%d")
        preds = _fetch_noaa_tide_predictions(config["tide_id"], begin, range_hours=48)
        if not preds:
            yesterday = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")
            preds = _fetch_noaa_tide_predictions(config["tide_id"], yesterday, range_hours=96)
        if not preds:
            return fallback

        now_str = now.strftime("%Y-%m-%d %H:%M")
        future = [p for p in preds if p["t"] >= now_str]
        if not future:
            future = [p for p in preds if p["t"] >= (now - datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")][-3:]
        if not future:
            future = preds[-3:]

        next_tide = future[0]
        next_type = "High" if next_tide["type"] == "H" else "Low"
        time_obj = datetime.datetime.strptime(next_tide["t"], "%Y-%m-%d %H:%M")
        next_event_string = f"Next {next_type} Tide {_format_time_12h(time_obj)}"

        return {
            "predictions": future[:3],
            "water_temp": water_temp,
            "water_temp_source": water_temp_source,
            "current_status": f"{'High' if future[0]['type'] == 'L' else 'Low'} Tide",
            "trend": "Rising" if future[0]["type"] == "H" else "Falling",
            "next_event": next_event_string,
            "source": f"NOAA {config['tide_id']} ({dist})",
        }
    except Exception as e:
        print(f"[WARN] tide fetch {config.get('name', config['tide_id'])}: {e}")
        return fallback

def _get_skywatch():
    try:
        p = phase(datetime.date.today())
        names = ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"]
        idx = 0
        if p < 1:
            idx = 0
        elif p < 6.9:
            idx = 1
        elif p < 7.1:
            idx = 2
        elif p < 13.9:
            idx = 3
        elif p < 14.1:
            idx = 4
        elif p < 20.9:
            idx = 5
        elif p < 21.1:
            idx = 6
        else:
            idx = 7
        return {
            "moon_phase": names[idx],
            "illumination": f"{round((1 - abs(p - 14)/14) * 100)}%",
            "planets_visible": "Check after sunset",
            "upcoming_event": "Low moonlight improves dawn hunting on fossil beaches",
        }
    except Exception:
        return {"moon_phase": "Unknown", "illumination": "--", "planets_visible": "Unknown", "upcoming_event": "N/A"}

def _get_daily_outlook(wave_ft: float, wind_mph: float, red_tide: str, mote: dict, forecast: dict) -> dict:
    summary = forecast.get("summary", "").lower()
    timing = "Good for daytime activities."
    periods = forecast.get("periods", [])
    if periods:
        txt = periods[0].get("detailedForecast", "").lower()
        if "thunderstorms" in txt:
            if "before" in txt:
                timing = f"Ideal window before {txt.split('before')[-1].split('.')[0].strip()} storms."
            elif "after" in txt:
                timing = f"Best before {txt.split('after')[-1].split('.')[0].strip()} weather transition."
            else:
                timing = "Avoid water during active storms."
        elif "sunny" in txt or "clear" in txt:
            timing = "Perfect full-day window."
    
    reason = f"Gulf conditions with {wave_ft:.1f}ft waves. {timing}"
    if red_tide == "Medium/High" or wave_ft > 6.0:
        return {"label": "DOUBLE RED", "vibe": "Water Closed", "color": "#7f1d1d", "reason": f"High hazard surge or biological risk. {timing}"}
    if wave_ft > 4.0 or wind_mph > 25 or red_tide != "Not Present":
        return {"label": "RED FLAG", "vibe": "High Hazard", "color": "#f87171", "reason": f"Dangerous conditions ({wave_ft:.1f}ft waves) or Red Tide. {timing}"}
    if "jellyfish" in str(mote).lower() and "none" not in str(mote).lower():
        return {"label": "PURPLE FLAG", "vibe": "Stinging Life", "color": "#a855f7", "reason": f"Stinging marine life present. {reason}"}
    if wave_ft > 1.5 or wind_mph > 12:
        return {"label": "YELLOW FLAG", "vibe": "Medium Hazard", "color": "#facc15", "reason": f"Moderate surf ({wave_ft:.1f}ft). Caution recommended. {timing}"}
    return {"label": "GREEN FLAG", "vibe": "Low Hazard", "color": "#4ade80", "reason": reason}

def _compute_shark_teeth_score(config: dict, wave_ft: float, tides: dict, mote: dict) -> Optional[dict]:
    if not config.get("shark_teeth"):
        return None
    score = 5
    tips: List[str] = []
    if wave_ft < 1.0:
        score += 2
        tips.append("Calm surf exposes shell layers")
    elif wave_ft < 1.5:
        score += 1
    elif wave_ft > 2.5:
        score -= 2
        tips.append("Higher surf buries fossils")
    if tides.get("trend") == "Falling":
        score += 2
        tips.append("Falling tide — prime shark-tooth window")
    elif tides.get("trend") == "Rising":
        score -= 1
    if mote.get("water") == "Clear Water":
        score += 1
    if str(mote.get("jellyfish", "None")).lower() != "none":
        score -= 1
    score = max(1, min(10, score))
    label = "Excellent" if score >= 8 else "Good" if score >= 6 else "Fair" if score >= 4 else "Poor"
    return {
        "score": score,
        "label": label,
        "tip": tips[0] if tips else "Best after low tide with light surf",
    }

# --- UNIFIED CORE FUNCTION ---
def refresh_one_beach(beach_id: str) -> dict:
    if beach_id not in BEACH_CONFIG:
        beach_id = "venice"
    config = BEACH_CONFIG[beach_id]
    try:
        wave_ft, period, sst_f = _get_marine_data(config)
        temp_f, wind_mph, wind_dir = _get_nws_obs(config)
        mote = _get_mote_report(config)
        red_tide = _get_red_tide_status(config)
        forecast = _get_nws_forecast(config)
        forecast["radar_proximity"] = _get_radar_proximity(config["lat"], config["lon"])
        tides = _get_tide_data(config, modeled_sst_f=sst_f)
        
        flag = calculate_flag(wave_ft, wind_mph, red_tide, mote["jellyfish"].lower() != "none")

        data = {
            "beach": config["name"],
            "lat": config["lat"],
            "lon": config["lon"],
            "timestamp": _fl_now().isoformat(),
            "timezone": "America/New_York",
            "tides": tides,
            "forecast": forecast,
            "skywatch": _get_skywatch(),
            "surf": {
                "height": round(wave_ft, 1),
                "period": period,
                "intensity": mote["intensity"],
                "type": mote["type"],
                "rip_current": forecast["rip_current"]
            },
            "weather": {"temp_f": temp_f, "wind_mph": wind_mph, "wind_dir": wind_dir},
            "red_tide": {"status": red_tide},
            "mote_extras": mote,
            "outlook": _build_outlook(flag, wave_ft, wind_mph, red_tide, mote, forecast),
            "teeth": _compute_shark_teeth_score(config, wave_ft, tides, mote),
            "clarity": {"label": "Good" if wave_ft < 1.5 else "Fair", "feet": round(max(1, 15 - (wave_ft * 4)), 0)}
        }
        GLOBAL_DATA_STORE[beach_id] = data
        return data
    except Exception as e:
        print(f"[ERROR] refresh_one_beach {beach_id}: {e}")
        return {"error": str(e), "beach": BEACH_CONFIG.get(beach_id, {}).get("name", beach_id)}

# --- BACKGROUND TASK (defensive) ---
async def data_refresher_loop():
    print("[STARTUP] Background refresher loop started (defensive mode)")
    while True:
        try:
            print(f"[{datetime.datetime.now()}] Starting full beach sync...")
            for beach_id in BEACH_CONFIG:
                try:
                    await asyncio.to_thread(refresh_one_beach, beach_id)
                except Exception as e:
                    print(f"[WARN] refresh {beach_id} failed (non-fatal): {str(e)[:80]}")
            await asyncio.sleep(300)
        except Exception as e:
            print(f"[ERROR] refresher loop error (continuing): {e}")
            await asyncio.sleep(60)

async def _warm_cache_on_startup() -> None:
    print("[STARTUP] Warming beach cache for cold-start readiness...")
    for beach_id in BEACH_CONFIG:
        try:
            await asyncio.to_thread(refresh_one_beach, beach_id)
        except Exception as e:
            print(f"[WARN] warm cache {beach_id} failed (non-fatal): {str(e)[:80]}")
    print(f"[STARTUP] Cache warm complete ({len(GLOBAL_DATA_STORE)} beaches)")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[STARTUP] lifespan starting - launching background task defensively")
    try:
        asyncio.create_task(_warm_cache_on_startup())
        asyncio.create_task(data_refresher_loop())
    except Exception as e:
        print(f"[WARN] background task creation failed (non-fatal): {e}")
    yield

# --- FASTAPI + MCP SETUP (FastMCP 3.x + Render compatible) ---
mcp = FastMCP("MarineAgent", debug=True, auth=None)
sse_app = mcp.sse_app()
print("[STARTUP] sse_app created successfully")

app = FastAPI(title="MarineAgent API", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "MarineAgent Live", "mcp_endpoint": "/mcp", "api_endpoints": ["/api/beaches_with_flags", "/api/conditions/{beach_id}", "/api/rank"]}

app.mount("/mcp", sse_app)

# MCP Tool for AI agents (Grok / Gemini / Claude)
@mcp.tool()
def get_beach_conditions(beach: str = "venice") -> dict:
    """Return real-time coastal conditions for any SWFL beach. Supports paddling, swimming, beach safety decisions."""
    beach_id = get_beach_key(beach)
    if not beach_id or beach_id not in BEACH_CONFIG:
        beach_id = "venice"
    return refresh_one_beach(beach_id)

@mcp.tool()
def rank_beaches(activity: str = "paddling", limit: int = 5, beach_id: str = "venice", radius_miles: int = 50) -> dict:
    """Rank beaches for an activity near an anchor beach (default 50mi). Red tide beaches are fully deranked; purple flag / jellyfish heavily penalized."""
    return rank_beaches_data(activity=activity, limit=limit, beach_id=beach_id, radius_miles=radius_miles)

# --- API ROUTES FOR FRONTEND DASHBOARD ---
def _cache_age_seconds(data: dict) -> float:
    try:
        ts = datetime.datetime.fromisoformat(data["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=FL_TZ)
        return (_fl_now() - ts).total_seconds()
    except Exception:
        return float("inf")

async def _refresh_all_if_stale(max_age: int) -> None:
    if max_age <= 0:
        return
    stale = not GLOBAL_DATA_STORE
    if not stale:
        for data in GLOBAL_DATA_STORE.values():
            if _cache_age_seconds(data) > max_age:
                stale = True
                break
    if stale:
        for beach_id in BEACH_CONFIG:
            await asyncio.to_thread(refresh_one_beach, beach_id)

@app.get("/api/beaches_with_flags")
async def list_beaches_with_flags(max_age: int = 0):
    await _refresh_all_if_stale(max_age)
    res = []
    for k, v in BEACH_CONFIG.items():
        data = GLOBAL_DATA_STORE.get(k)
        outlook = data.get("outlook", {}) if data else {}
        res.append({
            "id": k,
            "name": v["name"],
            "lat": v["lat"],
            "lon": v["lon"],
            "color": outlook.get("color", "#4ade80"),
            "storm_badge": outlook.get("storm_badge", False),
            "radar_nearby": outlook.get("radar_nearby", False),
        })
    return res

@app.get("/api/conditions/{beach_id}")
async def get_beach_conditions_api(beach_id: str, max_age: int = 0):
    cached = GLOBAL_DATA_STORE.get(beach_id)
    if cached and (max_age <= 0 or _cache_age_seconds(cached) <= max_age):
        return cached
    return await asyncio.to_thread(refresh_one_beach, beach_id)

@app.get("/api/rank")
async def rank_beaches_api(
    activity: str = "paddling",
    when: str = "today",
    coast: str = "all",
    limit: int = 5,
    beach_id: Optional[str] = None,
    near_lat: Optional[float] = None,
    near_lon: Optional[float] = None,
    radius_miles: Optional[float] = None,
):
    if when != "today":
        raise HTTPException(status_code=400, detail="Only when=today is supported right now")
    if activity not in VALID_ACTIVITIES:
        raise HTTPException(status_code=400, detail=f"activity must be one of: {', '.join(sorted(VALID_ACTIVITIES))}")
    if beach_id and beach_id not in BEACH_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown beach_id: {beach_id}")
    if (near_lat is None) ^ (near_lon is None):
        raise HTTPException(status_code=400, detail="near_lat and near_lon must be provided together")
    if radius_miles is not None and radius_miles <= 0:
        raise HTTPException(status_code=400, detail="radius_miles must be positive")
    if not GLOBAL_DATA_STORE:
        for bid in BEACH_CONFIG:
            await asyncio.to_thread(refresh_one_beach, bid)
    return rank_beaches_data(
        activity=activity,
        limit=limit,
        beach_id=beach_id,
        near_lat=near_lat,
        near_lon=near_lon,
        radius_miles=radius_miles,
    )

@app.get("/health")
@app.get("/api/health")
async def health():
    cached = len(GLOBAL_DATA_STORE)
    ready = cached > 0
    return {
        "status": "ok" if cached >= len(BEACH_CONFIG) else ("warming" if ready else "starting"),
        "ready": ready,
        "fully_cached": cached >= len(BEACH_CONFIG),
        "beaches_cached": cached,
        "beaches_total": len(BEACH_CONFIG),
        "mcp_endpoint": "/mcp/sse",
    }

print("[STARTUP] FastAPI app created and ready - all beach data sources integrated")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[STARTUP] Starting uvicorn on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
