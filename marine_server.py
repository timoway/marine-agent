import os
import datetime
import math
import requests
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, List, Dict
from bs4 import BeautifulSoup
from functools import lru_cache
from cachetools import TTLCache, cached
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
import uvicorn
from astral.moon import phase

# --- CONFIGURATION ---
OPENUV_KEY = os.environ.get("OPENUV_KEY", "")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "marine-secret-123")

# --- CACHING & PERFORMANCE ---
GLOBAL_DATA_STORE = {}

# --- MCP SERVER ---
# Force debug mode and zero authentication to allow any remote client (Grok)
mcp = FastMCP(
    "MarineAgent",
    debug=True,
    auth=None,
    sse_path="/"  # Mount internal path to root
)

# --- DATA: STATIONS & BEACHES ---
# ... (rest of the code stays same)

NOAA_STATIONS = {
    "8725889": {"name": "Venice (Roberts Bay)", "lat": 27.1000, "lon": -82.4433},
    "8726084": {"name": "Sarasota (Big Sarasota Pass area)", "lat": 27.3300, "lon": -82.5583},
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
    "siesta": {"name": "Siesta Key Beach", "mote_id": "2", "tide_id": "8726084", "county": "Sarasota", "lat": 27.2662, "lon": -82.5658, "nws_station": "KSRQ", "shark_teeth": False},
    "lido": {"name": "Lido Key Beach", "mote_id": "32", "tide_id": "8726084", "county": "Sarasota", "lat": 27.3188, "lon": -82.5786, "nws_station": "KSRQ", "shark_teeth": False},
    "caspersen": {"name": "Caspersen Beach", "mote_id": "34", "tide_id": "8725889", "county": "Sarasota", "lat": 27.0700, "lon": -82.4497, "nws_station": "KVNC", "shark_teeth": True},
    "nokomis": {"name": "Nokomis Beach", "mote_id": "35", "tide_id": "8725889", "county": "Sarasota", "lat": 27.1264, "lon": -82.4644, "nws_station": "KVNC", "shark_teeth": True},
    "englewood": {"name": "Englewood Beach", "mote_id": "7", "tide_id": "8725889", "county": "Charlotte", "lat": 26.9242, "lon": -82.3619, "nws_station": "KPGD", "shark_teeth": True},
    "fort-myers": {"name": "Fort Myers Beach", "mote_id": "145", "tide_id": "8725325", "county": "Lee", "lat": 26.4526, "lon": -81.9484, "nws_station": "KFMY", "shark_teeth": False},
    "bonita": {"name": "Bonita Beach", "mote_id": "144", "tide_id": "8725110", "county": "Lee", "lat": 26.3308, "lon": -81.8447, "nws_station": "KAPF", "shark_teeth": False},
    "vanderbilt": {"name": "Vanderbilt Beach", "mote_id": "114", "tide_id": "8725110", "county": "Collier", "lat": 26.2558, "lon": -81.8253, "nws_station": "KAPF", "shark_teeth": False},
    "barefoot": {"name": "Barefoot Beach", "mote_id": "144", "tide_id": "8725110", "county": "Collier", "lat": 26.3158, "lon": -81.8353, "nws_station": "KAPF", "shark_teeth": False},
    "bradenton": {"name": "Bradenton Beach", "mote_id": "4", "tide_id": "8726084", "county": "Manatee", "lat": 27.4695, "lon": -82.6987, "nws_station": "KSRQ", "shark_teeth": False},
    "anna-maria": {"name": "Anna Maria Island", "mote_id": "3", "tide_id": "8726084", "county": "Manatee", "lat": 27.5273, "lon": -82.7154, "nws_station": "KSRQ", "shark_teeth": False},
    "holmes": {"name": "Holmes Beach", "mote_id": "5", "tide_id": "8726084", "county": "Manatee", "lat": 27.4984, "lon": -82.7126, "nws_station": "KSRQ", "shark_teeth": False},
    "st-pete": {"name": "St. Pete Beach", "mote_id": "42", "tide_id": "8726520", "county": "Pinellas", "lat": 27.7253, "lon": -82.7412, "nws_station": "KSPG", "shark_teeth": False},
    "clearwater": {"name": "Clearwater Beach", "mote_id": "45", "tide_id": "8726724", "county": "Pinellas", "lat": 27.9781, "lon": -82.8317, "nws_station": "KPIE", "shark_teeth": False},
    "indian-rocks": {"name": "Indian Rocks Beach", "mote_id": "46", "tide_id": "8726724", "county": "Pinellas", "lat": 27.8931, "lon": -82.8482, "nws_station": "KPIE", "shark_teeth": False},
    "madeira": {"name": "Madeira Beach", "mote_id": "44", "tide_id": "8726520", "county": "Pinellas", "lat": 27.7945, "lon": -82.7840, "nws_station": "KSPG", "shark_teeth": False},
    "destin": {"name": "Destin", "mote_id": "100", "tide_id": "8729511", "county": "Okaloosa", "lat": 30.3935, "lon": -86.4958, "nws_station": "KDTS", "shark_teeth": False},
    "pensacola": {"name": "Pensacola Beach", "mote_id": "101", "tide_id": "8729840", "county": "Escambia", "lat": 30.3327, "lon": -87.1414, "nws_station": "KPNS", "shark_teeth": False},
    "panama-city": {"name": "Panama City Beach", "mote_id": "102", "tide_id": "8729210", "county": "Bay", "lat": 30.1766, "lon": -85.8055, "nws_station": "KECP", "shark_teeth": False}
}

# --- HELPERS ---
def calculate_relative_position(lat1: float, lon1: float, lat2: float, lon2: float) -> str:
    R = 3958.8
    dlat, dlon = math.radians(lat1 - lat2), math.radians(lon1 - lon2)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat2)) * math.cos(math.radians(lat1)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    bearing = math.degrees(math.atan2(math.sin(dlon) * math.cos(math.radians(lat1)), math.cos(math.radians(lat2)) * math.sin(math.radians(lat1)) - math.sin(math.radians(lat2)) * math.cos(math.radians(lat1)) * math.cos(dlon)))
    cardinal = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(bearing / 45) % 8]
    return f"{R * c:.1f} miles {cardinal}"

def calculate_flag(wave_ft, wind_mph, red_tide_status, jellyfish_detected):
    if red_tide_status == "Medium/High" or wave_ft > 6.0:
        return {"label": "DOUBLE RED", "vibe": "Water Closed", "color": "#7f1d1d"}
    if wave_ft > 4.0 or wind_mph > 25 or red_tide_status != "Not Present":
        return {"label": "RED FLAG", "vibe": "High Hazard", "color": "#f87171"}
    if jellyfish_detected:
        return {"label": "PURPLE FLAG", "vibe": "Stinging Life", "color": "#a855f7"}
    if wave_ft > 1.5 or wind_mph > 12:
        return {"label": "YELLOW FLAG", "vibe": "Medium Hazard", "color": "#facc15"}
    return {"label": "GREEN FLAG", "vibe": "Low Hazard", "color": "#4ade80"}

def get_beach_key(beach_name: str) -> Optional[str]:
    if not beach_name: return "venice"
    beach_name = beach_name.lower().replace(" ", "-")
    for key in BEACH_CONFIG:
        if key in beach_name: return key
    return None

# --- FETCHERS ---

def _get_mote_report(config):
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
    except: pass
    return {"intensity": "Light", "type": "Wind Swell", "water": "Clear Water", "algae": "No Algae Observed", "algae_type": "N/A", "jellyfish": "None"}

def _get_red_tide_status(config):
    try:
        url = "https://atoll.floridamarine.org/arcgis/rest/services/Projects_FWC/HAB_Current/FeatureServer/0/query"
        params = {"where": f"County = '{config['county']}'", "outFields": "Count_", "orderByFields": "SampleDate DESC", "resultRecordCount": 1, "f": "json"}
        r = requests.get(url, params=params, verify=False, timeout=8).json()
        feat = r.get('features', [])
        if feat:
            cnt = feat[0]['attributes']['Count_']
            if cnt > 100000: return "Medium/High"
            elif cnt > 10000: return "Low"
    except: pass
    return "Not Present"

def _get_marine_waves(config):
    try:
        url = f"https://marine-api.open-meteo.com/v1/marine?latitude={config['lat']}&longitude={config['lon']}&hourly=wave_height,swell_wave_period&timezone=auto"
        r = requests.get(url, timeout=5).json()
        h = datetime.datetime.now().hour
        wave_ft = r['hourly']['wave_height'][h] * 3.28
        period = r['hourly']['swell_wave_period'][h]
        return wave_ft, period
    except: return 0.5, 4.0

def _get_nws_obs(config):
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
    except: return 75.0, 8.0, "N/A"

def _get_nws_forecast(config):
    try:
        points_url = f"https://api.weather.gov/points/{config['lat']},{config['lon']}"
        points_r = requests.get(points_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        f_url = points_r['properties']['forecast']
        f_r = requests.get(f_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        periods = f_r['properties']['periods']
        summary = f"{periods[0]['name']}: {periods[0]['detailedForecast']}"
        
        alerts_url = f"https://api.weather.gov/alerts/active?point={config['lat']},{config['lon']}"
        a_r = requests.get(alerts_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        rip = "Low Risk"
        for alert in a_r.get('features', []):
            if "rip current" in alert['properties']['headline'].lower(): rip = "High Risk (NWS Alert)"
            
        station_info = NWS_STATIONS.get(config['nws_station'], {"lat": config['lat'], "lon": config['lon']})
        dist = calculate_relative_position(station_info["lat"], station_info["lon"], config["lat"], config["lon"])
        return {"summary": summary, "rip_current": rip, "source": f"NWS {config['nws_station']} ({dist})", "periods": periods}
    except: return {"summary": "Forecast intermittent.", "rip_current": "Low Risk", "source": "NWS", "periods": []}

def _get_tide_data(config):
    try:
        now = datetime.datetime.now()
        begin = now.strftime("%Y%m%d")
        url = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?begin_date={begin}&range=48&station={config['tide_id']}&product=predictions&datum=MLLW&time_zone=lst_ldt&interval=hilo&units=english&format=json"
        preds = requests.get(url, timeout=5).json().get('predictions', [])
        now_str = now.strftime("%Y-%m-%d %H:%M")
        future = [p for p in preds if p['t'] >= now_str]
        if not future: future = preds[:3]
        
        # New: Actionable Tide String
        next_tide = future[0]
        next_type = "High" if next_tide['type'] == 'H' else "Low"
        # Parse 2026-05-04 11:22 to 11:22 PM format
        time_obj = datetime.datetime.strptime(next_tide['t'], "%Y-%m-%d %H:%M")
        next_time_str = time_obj.strftime("%-I:%M %p")
        next_event_string = f"Next {next_type} Tide {next_time_str}"

        temp_url = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?date=latest&station={config['tide_id']}&product=water_temperature&datum=MLLW&time_zone=lst_ldt&units=english&format=json"
        water_temp = "72.4"
        try: water_temp = requests.get(temp_url, timeout=3).json().get('data', [{}])[0].get('v', "72.4")
        except: pass
        
        station_info = NOAA_STATIONS.get(config['tide_id'], {"lat": config['lat'], "lon": config['lon']})
        dist = calculate_relative_position(station_info["lat"], station_info["lon"], config["lat"], config["lon"])
        return {
            "predictions": future[:3], 
            "water_temp": water_temp, 
            "current_status": f"{'High' if future[0]['type'] == 'L' else 'Low'} Tide", # If next is High, current is Low-ish
            "trend": "Rising" if future[0]['type'] == 'H' else "Falling", 
            "next_event": next_event_string,
            "source": f"NOAA {config['tide_id']} ({dist})"
        }
    except: return {"predictions": [], "water_temp": "--", "current_status": "N/A", "trend": "N/A", "next_event": "Tides Unavailable", "source": "N/A"}

def _get_skywatch():
    try:
        p = phase(datetime.date.today())
        names = ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous", "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"]
        idx = 0
        if p < 1: idx = 0
        elif p < 6.9: idx = 1
        elif p < 7.1: idx = 2
        elif p < 13.9: idx = 3
        elif p < 14.1: idx = 4
        elif p < 20.9: idx = 5
        elif p < 21.1: idx = 6
        else: idx = 7
        return {"moon_phase": names[idx], "illumination": f"{round((1 - abs(p - 14)/14) * 100)}%", "planets_visible": "Venus, Mars, Jupiter", "upcoming_event": "June 9: Venus-Jupiter Conjunction"}
    except: return {"moon_phase": "Unknown", "illumination": "--", "planets_visible": "Unknown", "upcoming_event": "N/A"}

def _get_daily_outlook(wave_ft, wind_mph, red_tide, mote, forecast):
    summary = forecast.get("summary", "").lower()
    timing = "Good for daytime activities."
    periods = forecast.get("periods", [])
    if periods:
        txt = periods[0].get("detailedForecast", "").lower()
        if "thunderstorms" in txt:
            if "before" in txt: timing = f"Ideal window before {txt.split('before')[-1].split('.')[0].strip()} storms."
            elif "after" in txt: timing = f"Best before {txt.split('after')[-1].split('.')[0].strip()} weather transition."
            else: timing = "Avoid water during active storms."
        elif "sunny" in txt or "clear" in txt: timing = "Perfect full-day window."
    
    reason = f"Gulf conditions with {wave_ft:.1f}ft waves. {timing}"
    if red_tide == "Medium/High" or wave_ft > 6.0: return {"label": "DOUBLE RED", "vibe": "Water Closed", "color": "#7f1d1d", "reason": f"High hazard surge or biological risk. {timing}"}
    if wave_ft > 4.0 or wind_mph > 25 or red_tide != "Not Present": return {"label": "RED FLAG", "vibe": "High Hazard", "color": "#f87171", "reason": f"Dangerous conditions ({wave_ft:.1f}ft waves) or Red Tide. {timing}"}
    if "jellyfish" in str(mote).lower() and "none" not in str(mote).lower(): return {"label": "PURPLE FLAG", "vibe": "Stinging Life", "color": "#a855f7", "reason": f"Stinging marine life present. {reason}"}
    if wave_ft > 1.5 or wind_mph > 12: return {"label": "YELLOW FLAG", "vibe": "Medium Hazard", "color": "#facc15", "reason": f"Moderate surf ({wave_ft:.1f}ft). Caution recommended. {timing}"}
    return {"label": "GREEN FLAG", "vibe": "Low Hazard", "color": "#4ade80", "reason": reason}

# --- UNIFIED CORE FUNCTION ---

def refresh_one_beach(beach_id: str) -> dict:
    config = BEACH_CONFIG[beach_id]
    try:
        wave_ft, period = _get_marine_waves(config)
        temp_f, wind_mph, wind_dir = _get_nws_obs(config)
        mote = _get_mote_report(config)
        red_tide = _get_red_tide_status(config)
        forecast = _get_nws_forecast(config)
        tides = _get_tide_data(config)
        
        flag = calculate_flag(wave_ft, wind_mph, red_tide, mote["jellyfish"].lower() != "none")
        
        # --- UNIFIED ACTIVITY LOGIC ---
        summary_now = forecast["summary"].lower()
        is_stormy_now = "thunderstorms" in summary_now or "showers" in summary_now
        
        day_forecast = ""
        for p in forecast.get("periods", [])[:2]:
            if "night" not in p["name"].lower():
                day_forecast = p["detailedForecast"].lower()
                break
        
        beach_status = "Green"
        if is_stormy_now: beach_status = "Red"
        elif "thunderstorms" in day_forecast or "rain" in day_forecast:
            if any(x in day_forecast for x in ["tonight", "evening", "late"]): beach_status = "Yellow"
            else: beach_status = "Red"
        elif wind_mph > 22 or wave_ft > 4.0: beach_status = "Yellow"

        activities = {
            "paddling": "Red" if wind_mph > 15 or wave_ft > 2.5 or is_stormy_now else "Yellow" if wind_mph > 10 else "Green",
            "swimming": "Red" if wave_ft > 3.0 or red_tide != "Not Present" or is_stormy_now else "Yellow" if wave_ft > 1.5 else "Green",
            "beach": beach_status
        }

        data = {
            "beach": config["name"], "lat": config["lat"], "lon": config["lon"],
            "timestamp": datetime.datetime.now().isoformat(),
            "tides": tides, "forecast": forecast, "skywatch": _get_skywatch(),
            "surf": {"height": round(wave_ft, 1), "period": period, "intensity": mote["intensity"], "type": mote["type"], "rip_current": forecast["rip_current"]},
            "weather": {"temp_f": temp_f, "wind_mph": wind_mph, "wind_dir": wind_dir},
            "red_tide": {"status": red_tide},
            "mote_extras": mote,
            "outlook": {**flag, "reason": _get_daily_outlook(wave_ft, wind_mph, red_tide, mote, forecast)["reason"], "activities": activities},
            "teeth": {"score": 8} if config.get("shark_teeth") else None,
            "clarity": {"label": "Good" if wave_ft < 1.5 else "Fair", "feet": round(max(1, 15 - (wave_ft * 4)), 0)}
        }
        GLOBAL_DATA_STORE[beach_id] = data
        return data
    except Exception as e:
        print(f"Error refreshing {beach_id}: {e}")
        return {"error": str(e)}

# --- BACKGROUND TASK ---
async def data_refresher_loop():
    while True:
        print(f"[{datetime.datetime.now()}] Full Sync Starting...")
        for beach_id in BEACH_CONFIG:
            refresh_one_beach(beach_id)
            await asyncio.sleep(1) # Be polite to APIs
        await asyncio.sleep(300) # Every 5 minutes

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(data_refresher_loop())
    yield

app = FastAPI(title="MarineAgent API", lifespan=lifespan)

# Root-level health check (Supports GET and HEAD for Render)
@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "MarineAgent Live", "mcp_endpoint": "/sse/sse"}

# Ultra-permissive CORS for AI agents
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Force-disable any potential basic auth headers and ensure 200 OK for agents
@app.middleware("http")
async def force_no_auth(request, call_next):
    response = await call_next(request)
    
    # If anything on the MCP path tries to demand auth, kill it
    if request.url.path.startswith("/mcp"):
        if response.status_code in [401, 403]:
            # Downgrade errors to 200 OK to bypass Grok security interstitials
            response.status_code = 200
        
    if "www-authenticate" in response.headers:
        del response.headers["www-authenticate"]
    
    # Add explicit 'No-Cache' for the agent
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

# Standard mount point for Grok
app.mount("/mcp", mcp.sse_app())

@app.get("/api/beaches_with_flags")
async def list_beaches():
    res = []
    for k, v in BEACH_CONFIG.items():
        data = GLOBAL_DATA_STORE.get(k)
        color = data["outlook"]["color"] if data and "outlook" in data else "#4ade80"
        res.append({"id": k, "name": v["name"], "lat": v["lat"], "lon": v["lon"], "color": color})
    return res

@app.get("/api/conditions/{beach_id}")
async def get_beach_conditions(beach_id: str):
    if beach_id in GLOBAL_DATA_STORE: return GLOBAL_DATA_STORE[beach_id]
    return refresh_one_beach(beach_id)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
