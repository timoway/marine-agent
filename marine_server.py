import os
import re
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
from fastapi import FastAPI, HTTPException, Header, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
import uvicorn
from astral.moon import phase

import cache_store
import reports

print("[STARTUP] marine_server.py loading...")

# --- CONFIGURATION ---
FL_TZ = ZoneInfo("America/New_York")
OPENUV_KEY = os.environ.get("OPENUV_KEY", "")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "marine-secret-123")

def _fl_now() -> datetime.datetime:
    return datetime.datetime.now(FL_TZ)

# --- CACHING & PERFORMANCE ---
GLOBAL_DATA_STORE: Dict[str, dict] = {}
SAFETY_DISCLAIMER = (
    "Advisory only — verify official beach flags, lifeguards, and NWS alerts before entering the water."
)
FWC_HAB_URL = (
    "https://services7.arcgis.com/4RQmZZ0yaZkGR1zy/arcgis/rest/services/"
    "HAB_KbrevisPROD_View/FeatureServer/0/query"
)
MOTE_GQL_URL = "https://api.visitbeaches.org/graphql"
MOTE_BEACH_QUERY = """
query GetBeach($id: ID!) {
  beach(id: $id) {
    id
    name
    lastThreeDaysOfReports {
      id
      createdAt
      beachReport {
        parameterCategory { name }
        reportParameters {
          parameter { name }
          display
          value
        }
      }
    }
  }
}
"""
DATA_STALE_SECONDS = 300


def _source_meta(ok: bool, source_url: str = "", error: Optional[str] = None) -> dict:
    meta = {
        "fetched_at": _fl_now().isoformat(),
        "ok": ok,
        "stale": False,
        "source_url": source_url,
    }
    if error:
        meta["error"] = error
    return meta


def _red_tide_status_str(red_tide) -> str:
    if isinstance(red_tide, dict):
        return red_tide.get("status", "Unknown")
    return red_tide or "Unknown"


def _collect_unknown_sources(data: dict) -> List[str]:
    unknown = []
    checks = (
        ("red_tide", data.get("red_tide", {})),
        ("weather", data.get("weather", {})),
        ("forecast", data.get("forecast", {})),
        ("tides", data.get("tides", {})),
        ("mote", data.get("mote_extras", {})),
    )
    for name, block in checks:
        meta = block.get("meta", {}) if isinstance(block, dict) else {}
        if meta and not meta.get("ok", True):
            unknown.append(name)
    red_status = _red_tide_status_str(data.get("red_tide", {}))
    if red_status == "Unknown" and "red_tide" not in unknown:
        unknown.append("red_tide")
    return unknown


def _build_data_quality(data: dict, *, from_redis: bool = False) -> dict:
    age = _cache_age_seconds(data)
    unknown_sources = _collect_unknown_sources(data)
    return {
        "unknown_sources": unknown_sources,
        "has_unknowns": len(unknown_sources) > 0,
        "stale": age > DATA_STALE_SECONDS,
        "age_seconds": round(age, 1),
        "disclaimer": SAFETY_DISCLAIMER,
        "cached_from_redis": from_redis,
    }


def _store_beach_data(beach_id: str, data: dict) -> dict:
    data["data_quality"] = _build_data_quality(data)
    GLOBAL_DATA_STORE[beach_id] = data
    cache_store.write_beach(beach_id, data)
    return data

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
    "KECP": {"name": "NW Florida Beaches Intl", "lat": 30.35, "lon": -85.79},
    "KMIA": {"name": "Miami Intl", "lat": 25.79056, "lon": -80.31639},
    "KFLL": {"name": "Fort Lauderdale-Hollywood Intl", "lat": 26.07874, "lon": -80.1622},
    "KPMP": {"name": "Pompano Beach Airpark", "lat": 26.24556, "lon": -80.11139},
    "KBCT": {"name": "Boca Raton Airport", "lat": 26.37861, "lon": -80.10778},
    "KPBI": {"name": "Palm Beach Intl", "lat": 26.6851, "lon": -80.09919},
    "KVRB": {"name": "Vero Beach Municipal", "lat": 27.65556, "lon": -80.41806},
    "KCOI": {"name": "Merritt Island Airport", "lat": 28.3422, "lon": -80.68407},
    "KDAB": {"name": "Daytona Beach Intl", "lat": 29.17354, "lon": -81.07186},
    "KSGJ": {"name": "Northeast Florida Regional (St. Augustine)", "lat": 29.95924, "lon": -81.34105},
    "KCRG": {"name": "Jacksonville Craig Municipal", "lat": 30.33709, "lon": -81.51275}
}

BEACH_CONFIG = {
    "venice": {"name": "Venice Beach", "mote_id": "6", "tide_id": "8725889", "county": "Sarasota", "lat": 27.1001, "lon": -82.4542, "nws_station": "KVNC", "shark_teeth": True, "coast": "gulf"},
    "manasota-key": {"name": "Manasota Key Beach", "mote_id": "3", "tide_id": "8725889", "county": "Sarasota", "lat": 27.0125, "lon": -82.4131, "nws_station": "KVNC", "shark_teeth": True, "coast": "gulf"},
    "siesta": {"name": "Siesta Key Beach", "mote_id": "2", "tide_id": "8726034", "county": "Sarasota", "lat": 27.2662, "lon": -82.5658, "nws_station": "KSRQ", "shark_teeth": False, "coast": "gulf"},
    "lido": {"name": "Lido Key Beach", "mote_id": "4", "tide_id": "8726034", "county": "Sarasota", "lat": 27.3188, "lon": -82.5786, "nws_station": "KSRQ", "shark_teeth": False, "coast": "gulf"},
    "caspersen": {"name": "Caspersen Beach", "mote_id": "40", "tide_id": "8725889", "county": "Sarasota", "lat": 27.0700, "lon": -82.4497, "nws_station": "KVNC", "shark_teeth": True, "coast": "gulf"},
    "nokomis": {"name": "Nokomis Beach", "mote_id": "5", "tide_id": "8725889", "county": "Sarasota", "lat": 27.1264, "lon": -82.4644, "nws_station": "KVNC", "shark_teeth": True, "coast": "gulf"},
    "englewood": {"name": "Englewood Beach", "mote_id": "42", "tide_id": "8725889", "county": "Charlotte", "lat": 26.9242, "lon": -82.3619, "nws_station": "KPGD", "shark_teeth": True, "coast": "gulf"},
    "fort-myers": {"name": "Fort Myers Beach", "mote_id": "11", "tide_id": "8725325", "county": "Lee", "lat": 26.4526, "lon": -81.9484, "nws_station": "KFMY", "shark_teeth": False, "coast": "gulf"},
    "bonita": {"name": "Bonita Beach", "mote_id": "14", "tide_id": "8725110", "county": "Lee", "lat": 26.3308, "lon": -81.8447, "nws_station": "KAPF", "shark_teeth": False, "coast": "gulf"},
    "vanderbilt": {"name": "Vanderbilt Beach", "mote_id": "29", "tide_id": "8725110", "county": "Collier", "lat": 26.2558, "lon": -81.8253, "nws_station": "KAPF", "shark_teeth": False, "coast": "gulf"},
    "barefoot": {"name": "Barefoot Beach", "mote_id": "28", "tide_id": "8725110", "county": "Collier", "lat": 26.3158, "lon": -81.8353, "nws_station": "KAPF", "shark_teeth": False, "coast": "gulf"},
    "bradenton": {"name": "Bradenton Beach", "mote_id": "64", "tide_id": "8726243", "county": "Manatee", "lat": 27.4695, "lon": -82.6987, "nws_station": "KSRQ", "shark_teeth": False, "coast": "gulf"},
    "anna-maria": {"name": "Anna Maria Island", "mote_id": "62", "tide_id": "8726282", "county": "Manatee", "lat": 27.5273, "lon": -82.7154, "nws_station": "KSRQ", "shark_teeth": False, "coast": "gulf"},
    "holmes": {"name": "Holmes Beach", "mote_id": "142", "tide_id": "8726243", "county": "Manatee", "lat": 27.4984, "lon": -82.7126, "nws_station": "KSRQ", "shark_teeth": False, "coast": "gulf"},
    "st-pete": {"name": "St. Pete Beach", "mote_id": "35", "tide_id": "8726520", "county": "Pinellas", "lat": 27.7253, "lon": -82.7412, "nws_station": "KSPG", "shark_teeth": False, "coast": "gulf"},
    "clearwater": {"name": "Clearwater Beach", "mote_id": "7", "tide_id": "8726724", "county": "Pinellas", "lat": 27.9781, "lon": -82.8317, "nws_station": "KPIE", "shark_teeth": False, "coast": "gulf"},
    "indian-rocks": {"name": "Indian Rocks Beach", "mote_id": "33", "tide_id": "8726724", "county": "Pinellas", "lat": 27.8931, "lon": -82.8482, "nws_station": "KPIE", "shark_teeth": False, "coast": "gulf"},
    "madeira": {"name": "Madeira Beach", "mote_id": "34", "tide_id": "8726520", "county": "Pinellas", "lat": 27.7945, "lon": -82.7840, "nws_station": "KSPG", "shark_teeth": False, "coast": "gulf"},
    "destin": {"name": "Destin", "mote_id": "19", "tide_id": "8729511", "county": "Okaloosa", "lat": 30.3935, "lon": -86.4958, "nws_station": "KDTS", "shark_teeth": False, "coast": "gulf"},
    "pensacola": {"name": "Pensacola Beach", "mote_id": "18", "tide_id": "8729840", "county": "Escambia", "lat": 30.3327, "lon": -87.1414, "nws_station": "KPNS", "shark_teeth": False, "coast": "gulf"},
    "panama-city": {"name": "Panama City Beach", "mote_id": "73", "tide_id": "8729210", "county": "Bay", "lat": 30.1766, "lon": -85.8055, "nws_station": "KECP", "shark_teeth": False, "coast": "gulf"},
    "naples": {"name": "Naples Pier", "mote_id": "49", "tide_id": "8725110", "county": "Collier", "lat": 26.1421, "lon": -81.8077, "nws_station": "KAPF", "shark_teeth": False, "coast": "gulf"},
    "marco-island": {"name": "Tigertail Beach", "mote_id": "43", "tide_id": "8725110", "county": "Collier", "lat": 25.9764, "lon": -81.7284, "nws_station": "KMKY", "shark_teeth": False, "coast": "gulf"},
    "south-marco": {"name": "South Marco Beach", "mote_id": "31", "tide_id": "8725110", "county": "Collier", "lat": 25.9298, "lon": -81.7196, "nws_station": "KMKY", "shark_teeth": False, "coast": "gulf"},
    "brohard": {"name": "Brohard Paw Park", "mote_id": "132", "tide_id": "8725889", "county": "Sarasota", "lat": 27.0691, "lon": -82.4471, "nws_station": "KVNC", "shark_teeth": True, "coast": "gulf"},
    "honeymoon-island": {"name": "Honeymoon Island Dog Beach", "mote_id": "17", "tide_id": "8726761", "county": "Pinellas", "lat": 28.0550, "lon": -82.8186, "nws_station": "KPIE", "shark_teeth": False, "coast": "gulf"},
    "miami-beach": {"name": "Miami Beach", "mote_id": "", "tide_id": "8723214", "county": "Miami-Dade", "lat": 25.7826, "lon": -80.1300, "nws_station": "KMIA", "shark_teeth": False, "coast": "atlantic"},
    "fort-lauderdale": {"name": "Fort Lauderdale Beach", "mote_id": "", "tide_id": "8722899", "county": "Broward", "lat": 26.1224, "lon": -80.1037, "nws_station": "KFLL", "shark_teeth": False, "coast": "atlantic"},
    "hollywood-beach": {"name": "Hollywood Beach", "mote_id": "", "tide_id": "8722979", "county": "Broward", "lat": 26.0112, "lon": -80.1178, "nws_station": "KFLL", "shark_teeth": False, "coast": "atlantic"},
    "pompano-beach": {"name": "Pompano Beach", "mote_id": "74", "tide_id": "8722899", "county": "Broward", "lat": 26.2380, "lon": -80.0937, "nws_station": "KPMP", "shark_teeth": False, "coast": "atlantic"},
    "boca-raton": {"name": "Boca Raton Beach", "mote_id": "", "tide_id": "8722816", "county": "Palm Beach", "lat": 26.3475, "lon": -80.0656, "nws_station": "KBCT", "shark_teeth": False, "coast": "atlantic"},
    "delray-beach": {"name": "Delray Beach", "mote_id": "", "tide_id": "8722746", "county": "Palm Beach", "lat": 26.4614, "lon": -80.0645, "nws_station": "KBCT", "shark_teeth": False, "coast": "atlantic"},
    "lake-worth-beach": {"name": "Lake Worth Beach", "mote_id": "37", "tide_id": "8722670", "county": "Palm Beach", "lat": 26.6161, "lon": -80.0331, "nws_station": "KPBI", "shark_teeth": False, "coast": "atlantic"},
    "palm-beach": {"name": "Palm Beach", "mote_id": "", "tide_id": "8722607", "county": "Palm Beach", "lat": 26.7056, "lon": -80.0364, "nws_station": "KPBI", "shark_teeth": False, "coast": "atlantic"},
    "jupiter-beach": {"name": "Jupiter Beach", "mote_id": "", "tide_id": "8722495", "county": "Palm Beach", "lat": 26.9342, "lon": -80.0733, "nws_station": "KPBI", "shark_teeth": False, "coast": "atlantic"},
    "vero-beach": {"name": "Vero Beach", "mote_id": "", "tide_id": "8722105", "county": "Indian River", "lat": 27.6386, "lon": -80.3684, "nws_station": "KVRB", "shark_teeth": False, "coast": "atlantic"},
    "cocoa-beach": {"name": "Cocoa Beach", "mote_id": "", "tide_id": "8721649", "county": "Brevard", "lat": 28.3200, "lon": -80.6076, "nws_station": "KCOI", "shark_teeth": False, "coast": "atlantic"},
    "daytona-beach": {"name": "Daytona Beach", "mote_id": "", "tide_id": "8721120", "county": "Volusia", "lat": 29.2108, "lon": -81.0228, "nws_station": "KDAB", "shark_teeth": False, "coast": "atlantic"},
    "st-augustine-beach": {"name": "St. Augustine Beach", "mote_id": "", "tide_id": "8720587", "county": "St. Johns", "lat": 29.8508, "lon": -81.2648, "nws_station": "KSGJ", "shark_teeth": False, "coast": "atlantic"},
    "jacksonville-beach": {"name": "Jacksonville Beach", "mote_id": "38", "tide_id": "8720291", "county": "Duval", "lat": 30.2947, "lon": -81.3931, "nws_station": "KCRG", "shark_teeth": False, "coast": "atlantic"},
}

# Beach Pulse (community reports) is on for every beach by default (see plan.md
# cold-start reasoning). To disable a specific beach, set "reports_enabled": False
# on its entry above — this loop won't override an explicit value.
for _cfg in BEACH_CONFIG.values():
    _cfg.setdefault("reports_enabled", True)

# --- BEACH AMENITIES (docs/roadmap-ios-launch.md Track 3 — "know before you go") ---
# Static curated facts, kept separate from BEACH_CONFIG (which is live-fetch
# wiring). parking: "free" | "paid" | "none"; lifeguard: "year_round" |
# "seasonal" | "none". FIRST PASS based on general public knowledge as of
# 2026-07 — fees, seasons, and off-leash rules drift over time in ways that
# can't be verified the way the NOAA/NWS station IDs above were (those were
# checked live against the actual APIs). Owner should spot-check before
# relying on this for launch, per the original Track 3 plan ("owner curates").
BEACH_AMENITIES = {
    "venice": {"parking": "free", "parking_notes": "Free lots along Harbor Dr; fill on weekends", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "manasota-key": {"parking": "free", "parking_notes": "Limited free lots", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "none"},
    "siesta": {"parking": "free", "parking_notes": "Large free lots; fill by mid-morning in season", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "year_round"},
    "lido": {"parking": "paid", "parking_notes": "Pavilion lot, metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "caspersen": {"parking": "free", "parking_notes": "Free lot", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "none"},
    "nokomis": {"parking": "free", "parking_notes": "Free lot", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "englewood": {"parking": "paid", "parking_notes": "Metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "fort-myers": {"parking": "paid", "parking_notes": "Metered lots", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "bonita": {"parking": "paid", "parking_notes": "Metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "vanderbilt": {"parking": "paid", "parking_notes": "County parking garage", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "barefoot": {"parking": "paid", "parking_notes": "Nature preserve — county park entry fee", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "none"},
    "bradenton": {"parking": "free", "parking_notes": "Free street parking", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "anna-maria": {"parking": "free", "parking_notes": "Free street parking, limited", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "holmes": {"parking": "free", "parking_notes": "Free street parking, limited", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "st-pete": {"parking": "paid", "parking_notes": "Metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "clearwater": {"parking": "paid", "parking_notes": "Garage + metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "year_round"},
    "indian-rocks": {"parking": "free", "parking_notes": "Limited street parking", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "none"},
    "madeira": {"parking": "paid", "parking_notes": "Metered, John's Pass area", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "destin": {"parking": "paid", "parking_notes": "Public beach access lots", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "pensacola": {"parking": "free", "parking_notes": "Escambia County beach parking is free", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "panama-city": {"parking": "free", "parking_notes": "Many free county beach accesses", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "naples": {"parking": "paid", "parking_notes": "Metered street parking near the pier", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "marco-island": {"parking": "paid", "parking_notes": "County park entry fee", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "none"},
    "south-marco": {"parking": "free", "parking_notes": "Limited street parking", "dog_friendly": False, "dog_notes": None, "restrooms": False, "lifeguard": "none"},
    "brohard": {"parking": "free", "parking_notes": "Free lot at the paw park", "dog_friendly": True, "dog_notes": "OSM-confirmed off-leash dog park (leisure=dog_park) — Sarasota County dog beach tag required for non-residents", "restrooms": True, "lifeguard": "none"},
    "honeymoon-island": {"parking": "paid", "parking_notes": "Florida State Park entry fee applies", "dog_friendly": True, "dog_notes": "OSM-confirmed off-leash dog park (leisure=dog_park) inside Honeymoon Island State Park, Dunedin", "restrooms": True, "lifeguard": "none"},
    "miami-beach": {"parking": "paid", "parking_notes": "Metered + garages", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "year_round"},
    "fort-lauderdale": {"parking": "paid", "parking_notes": "Metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "hollywood-beach": {"parking": "paid", "parking_notes": "Metered along the Broadwalk", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "pompano-beach": {"parking": "paid", "parking_notes": "Metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "boca-raton": {"parking": "paid", "parking_notes": "Resident/non-resident rate lots", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "delray-beach": {"parking": "paid", "parking_notes": "Metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "lake-worth-beach": {"parking": "paid", "parking_notes": "Metered lot at the pier", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "palm-beach": {"parking": "paid", "parking_notes": "Limited metered", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "jupiter-beach": {"parking": "free", "parking_notes": "Free county park lot", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "vero-beach": {"parking": "free", "parking_notes": "Free lots", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "cocoa-beach": {"parking": "free", "parking_notes": "Free lots", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "daytona-beach": {"parking": "paid", "parking_notes": "Beach driving/parking permit in some areas", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "year_round"},
    "st-augustine-beach": {"parking": "free", "parking_notes": "Some beach-driving areas require a permit", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "seasonal"},
    "jacksonville-beach": {"parking": "free", "parking_notes": "Free public lots", "dog_friendly": False, "dog_notes": None, "restrooms": True, "lifeguard": "year_round"},
}
for _bid in BEACH_CONFIG:
    BEACH_AMENITIES.setdefault(_bid, {"parking": "unknown", "parking_notes": None, "dog_friendly": False, "dog_notes": None, "restrooms": None, "lifeguard": "unknown"})

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

def _format_hour_short(dt: datetime.datetime) -> str:
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour} {suffix}"

def _time_of_day_bucket(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "overnight"

def _verdict_title(bucket: str) -> str:
    if bucket in ("evening", "overnight"):
        return "Tonight's outlook"
    return "Today's outlook"

def _plan_panel_label(bucket: str) -> str:
    return {
        "morning": "Plan for today",
        "afternoon": "Plan for later",
        "evening": "Plan for tonight",
        "overnight": "Plan for overnight",
    }[bucket]

def _storm_timing_label(bucket: str, when: str) -> str:
    if when == "now":
        return {
            "morning": "this morning",
            "afternoon": "this afternoon",
            "evening": "tonight",
            "overnight": "overnight",
        }[bucket]
    return {
        "morning": "this afternoon",
        "afternoon": "tonight",
        "evening": "later tonight",
        "overnight": "overnight",
    }[bucket]

def _extract_before_time(text: str) -> Optional[str]:
    match = re.search(r"before\s+(\d{1,2})\s*(am|pm)", (text or "").lower())
    if not match:
        return None
    hour, suffix = match.groups()
    return f"before {int(hour)} {suffix.upper()}"

def _storm_chance_reason(likelihood: str, bucket: str, when: str, forecast_text: str = "") -> str:
    timing = _extract_before_time(forecast_text)
    if timing and when == "now" and bucket in ("evening", "overnight"):
        prefix = "Storms likely" if likelihood == "likely" else "Chance of showers and thunderstorms"
        return f"{prefix} {timing}"
    window = _storm_timing_label(bucket, when)
    if likelihood == "likely":
        return f"Storms likely {window}"
    if likelihood == "active":
        return f"Storm risk building toward {window}"
    if likelihood == "chance":
        return f"Showers or storms possible {window}"
    return f"Favorable conditions expected {window}"

def _period_relevance(name: str, hour: int) -> str:
    n = (name or "").lower()
    if "tonight" in n or "this evening" in n:
        return "now" if hour >= 18 else "later"
    if "overnight" in n:
        return "now" if hour >= 22 or hour < 5 else "later"
    if "afternoon" in n:
        if hour < 12:
            return "later"
        if hour < 18:
            return "now"
        return "skip"
    if "morning" in n:
        return "now" if hour < 12 else "skip"
    if n == "today":
        return "now" if hour < 18 else "skip"
    if "tomorrow" in n:
        return "later"
    return "now" if hour >= 12 else "later"

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
    if red_tide_status == "Unknown":
        return {"label": "YELLOW FLAG", "vibe": "Data Incomplete", "color": "#facc15"}
    if red_tide_status == "Medium/High" or wave_ft > 6.0:
        return {"label": "DOUBLE RED", "vibe": "Water Closed", "color": "#7f1d1d"}
    if wave_ft > 4.0 or wind_mph > 25 or red_tide_status not in ("Not Present", "Unknown"):
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
    hourly_lines = []
    for period in window[:3]:
        pop = period.get("probabilityOfPrecipitation", {}).get("value")
        if pop is not None:
            max_pop = max(max_pop, int(pop))
        short_fc = period.get("shortForecast", "")
        try:
            start = datetime.datetime.fromisoformat(period["startTime"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=FL_TZ)
            time_label = _format_hour_short(start)
        except (KeyError, ValueError, TypeError):
            time_label = ""
        rain_chance = int(pop) if pop is not None else None
        hourly_lines.append({
            "time": time_label,
            "forecast": short_fc,
            "rain_chance": rain_chance,
        })
        lvl = _pop_to_likelihood(pop, short_fc)
        if period is current or period in next_hours[:2]:
            now_likelihood = _max_likelihood(now_likelihood, lvl)

    summary_parts = []
    for line in hourly_lines:
        part = f"{line['time']}: {line['forecast']}" if line["time"] else line["forecast"]
        if line["rain_chance"] is not None and line["rain_chance"] > 0:
            part += f" ({line['rain_chance']}% chance of rain)"
        summary_parts.append(part)

    return {
        "now_likelihood": now_likelihood,
        "max_pop": max_pop,
        "current_short": current.get("shortForecast", "") if current else "",
        "hourly_lines": hourly_lines,
        "summary": "; ".join(summary_parts),
    }

def _period_start_date(period: dict) -> Optional[datetime.date]:
    try:
        start = datetime.datetime.fromisoformat(period["startTime"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=FL_TZ)
        else:
            start = start.astimezone(FL_TZ)
        return start.date()
    except (KeyError, ValueError, TypeError):
        return None

def _advisory_from_forecast(hazards: dict, active_alerts: list) -> tuple[str, str]:
    if hazards.get("hurricane_warning") or hazards.get("tropical_storm_warning") or hazards.get("tornado_warning"):
        return "severe", "Active NWS warning for tropical or severe weather"
    if hazards.get("special_marine_warning") or hazards.get("severe_thunderstorm_warning"):
        return "active", next(
            (a["headline"] for a in active_alerts if a["event"] in ("Special Marine Warning", "Severe Thunderstorm Warning")),
            "Active marine or severe thunderstorm warning",
        )
    if hazards.get("special_weather_statement"):
        return "active", next(
            (a["headline"] for a in active_alerts if a["event"] == "Special Weather Statement"),
            "NWS special weather statement for nearby storms",
        )
    if hazards.get("marine_weather_statement"):
        return "likely", next(
            (a["headline"] for a in active_alerts if a["event"] == "Marine Weather Statement"),
            "Marine weather statement in effect",
        )
    if hazards.get("hurricane_watch") or hazards.get("tropical_storm_watch"):
        return "likely", "Tropical weather watch in effect"
    return "none", ""

def _analyze_tomorrow_situation(forecast: dict) -> dict:
    now = _fl_now()
    target_date = now.date() + datetime.timedelta(days=1)
    periods = forecast.get("periods", [])
    hazards = forecast.get("hazards", {})
    active_alerts = forecast.get("active_alerts", [])
    advisory_level, advisory_reason = _advisory_from_forecast(hazards, active_alerts)

    day_text = ""
    night_text = ""
    day_period = None
    for period in periods:
        if _period_start_date(period) != target_date:
            continue
        name = period.get("name", "")
        text = period.get("detailedForecast", "")
        full = f"{name} {text}"
        if period.get("isDaytime", True):
            day_text += f" {full}"
            if day_period is None:
                day_period = period
        else:
            night_text += f" {full}"

    if not day_text.strip():
        weekday = target_date.strftime("%A").lower()
        for period in periods:
            name = (period.get("name") or "").lower()
            if weekday in name and "night" not in name:
                day_text = f"{period.get('name', '')} {period.get('detailedForecast', '')}"
                day_period = period
                break

    if not day_text.strip() and len(periods) > 2:
        day_text = periods[2].get("detailedForecast", "")
        day_period = periods[2]

    now_likelihood = _max_likelihood(_storm_likelihood_in_text(day_text))
    later_likelihood = _max_likelihood(_storm_likelihood_in_text(night_text))
    if day_period:
        forecast_headline = f"{day_period.get('name', target_date.strftime('%A'))}: {day_period.get('detailedForecast', '')}"
    else:
        forecast_headline = f"{target_date.strftime('%A')}: Forecast unavailable for tomorrow."

    return {
        "hour": 8,
        "time_bucket": "morning",
        "planning_horizon": "tomorrow",
        "verdict_title": "Tomorrow's outlook",
        "plan_label": "Plan for tomorrow",
        "advisory_level": advisory_level,
        "advisory_reason": advisory_reason,
        "now_likelihood": now_likelihood,
        "later_likelihood": later_likelihood,
        "forecast_headline": forecast_headline,
        "current_forecast_text": day_text.strip(),
        "hourly_summary": "",
        "hourly_lines": [],
        "hourly_max_pop": 0,
        "current_period": day_period.get("name", target_date.strftime("%A")) if day_period else target_date.strftime("%A"),
        "active_alerts": active_alerts,
        "radar_proximity": {},
    }

def _analyze_weather_situation(forecast: dict, when: str = "today") -> dict:
    if when == "tomorrow":
        return _analyze_tomorrow_situation(forecast)
    now = _fl_now()
    hour = now.hour
    time_bucket = _time_of_day_bucket(hour)
    periods = forecast.get("periods", [])
    hazards = forecast.get("hazards", {})
    active_alerts = forecast.get("active_alerts", [])
    advisory_level, advisory_reason = _advisory_from_forecast(hazards, active_alerts)

    current_text = ""
    later_text = ""
    current_period_name = ""
    for i, period in enumerate(periods[:4]):
        name = period.get("name", "")
        text = period.get("detailedForecast", "")
        full = f"{name} {text}"
        relevance = _period_relevance(name, hour)
        if relevance == "skip":
            continue
        if relevance == "now":
            current_text += f" {full}"
            if not current_period_name:
                current_period_name = name
        else:
            later_text += f" {full}"
        if i == 0 and not current_period_name and relevance == "now":
            current_period_name = name

    if not current_text.strip() and periods:
        current_text = periods[0].get("detailedForecast", "")
        current_period_name = periods[0].get("name", "")
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
        "time_bucket": time_bucket,
        "planning_horizon": "today",
        "verdict_title": _verdict_title(time_bucket),
        "plan_label": _plan_panel_label(time_bucket),
        "advisory_level": advisory_level,
        "advisory_reason": advisory_reason,
        "now_likelihood": now_likelihood,
        "later_likelihood": later_likelihood,
        "forecast_headline": summary,
        "current_forecast_text": current_text.strip(),
        "hourly_summary": hourly.get("summary", ""),
        "hourly_lines": hourly.get("hourly_lines", []),
        "hourly_max_pop": hourly.get("max_pop", 0),
        "current_period": current_period_name or (periods[0].get("name", "") if periods else ""),
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

def _forecast_tomorrow_plan_status(situation: dict) -> tuple[str, str]:
    advisory = situation["advisory_level"]
    if advisory in ("severe", "active"):
        return "Red", situation["advisory_reason"] or "Weather advisory in effect tomorrow"
    if advisory == "likely":
        return "Red", situation["advisory_reason"] or "Tropical weather threat tomorrow"

    now_lvl = situation["now_likelihood"]
    later_lvl = situation["later_likelihood"]
    if now_lvl in ("severe", "active"):
        return "Red", "Storms expected tomorrow"
    if now_lvl == "likely":
        return "Yellow", "Storms likely tomorrow — morning may be the best window"
    if now_lvl == "chance":
        return "Yellow", "Showers or storms possible tomorrow"
    if later_lvl in ("likely", "active"):
        return "Yellow", "Storms possible tomorrow evening"
    if later_lvl == "chance":
        return "Yellow", "Isolated storms possible tomorrow night"
    return "Green", "Favorable conditions expected tomorrow"

def _forecast_plan_status(situation: dict) -> tuple[str, str]:
    if situation.get("planning_horizon") == "tomorrow":
        return _forecast_tomorrow_plan_status(situation)
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
    bucket = situation.get("time_bucket", _time_of_day_bucket(situation["hour"]))
    forecast_text = f"{situation.get('current_forecast_text', '')} {situation.get('forecast_headline', '')}"

    if now_lvl in ("severe", "active"):
        return "Red", "Storms active or imminent right now"
    if now_lvl == "likely":
        return "Red", _storm_chance_reason("likely", bucket, "now", forecast_text)

    if bucket == "morning":
        if later_lvl == "likely":
            return "Yellow", "Storms likely this afternoon — best window is this morning"
        if later_lvl == "chance":
            return "Green", "Good conditions now — showers or storms possible this afternoon"
        if later_lvl == "active":
            return "Yellow", _storm_chance_reason("active", bucket, "later", forecast_text)
        return "Green", "Favorable conditions expected today"

    if now_lvl == "chance":
        return "Yellow", _storm_chance_reason("chance", bucket, "now", forecast_text)
    if later_lvl in ("likely", "active"):
        return "Yellow", _storm_chance_reason(later_lvl, bucket, "later", forecast_text)
    if later_lvl == "chance":
        return "Yellow", _storm_chance_reason("chance", bucket, "later", forecast_text)
    if bucket in ("evening", "overnight"):
        return "Green", "Conditions look favorable for the rest of tonight"
    return "Green", "Conditions look favorable for the rest of today"

def _physical_activity_status(activity: str, wave_ft: float, wind_mph: float, red_tide: str) -> tuple[str, str]:
    if red_tide == "Unknown":
        return "Yellow", "Red tide data unavailable — check FWC before going out"
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

def _forecast_tomorrow_activity_status(activity: str, situation: dict) -> tuple[str, str]:
    advisory = situation["advisory_level"]
    if advisory in ("severe", "active", "likely"):
        return "Red", situation["advisory_reason"] or "Weather advisory in effect tomorrow"

    now_lvl = situation["now_likelihood"]
    later_lvl = situation["later_likelihood"]
    if now_lvl in ("severe", "active", "likely"):
        return "Red", "Storms expected tomorrow"
    if now_lvl == "chance":
        return "Yellow", "Showers or storms possible tomorrow"
    if later_lvl in ("likely", "active", "chance"):
        return "Yellow", "Storm risk tomorrow evening or night"
    return "Green", "No significant storm risk forecast for tomorrow"

def _forecast_activity_status(activity: str, situation: dict) -> tuple[str, str]:
    if situation.get("planning_horizon") == "tomorrow":
        return _forecast_tomorrow_activity_status(activity, situation)
    advisory = situation["advisory_level"]
    if advisory in ("severe", "active", "likely"):
        return "Red", situation["advisory_reason"] or "Weather advisory in effect"

    radar_reason = _radar_plan_reason(situation)
    if radar_reason:
        return "Yellow", radar_reason

    now_lvl = situation["now_likelihood"]
    later_lvl = situation["later_likelihood"]
    bucket = situation.get("time_bucket", _time_of_day_bucket(situation["hour"]))
    forecast_text = f"{situation.get('current_forecast_text', '')} {situation.get('forecast_headline', '')}"

    if now_lvl in ("severe", "active", "likely"):
        return "Red", "Storms in the current period"

    if bucket == "morning":
        if later_lvl == "likely":
            return "Yellow", _storm_chance_reason("likely", bucket, "later", forecast_text)
        if later_lvl == "chance":
            return "Green", "Morning window before possible afternoon storms"
        return "Green", "No significant storm risk forecast"

    if now_lvl == "chance":
        return "Yellow", _storm_chance_reason("chance", bucket, "now", forecast_text)
    if later_lvl in ("likely", "active"):
        return "Yellow", _storm_chance_reason(later_lvl, bucket, "later", forecast_text)
    if later_lvl == "chance":
        return "Yellow", _storm_chance_reason("chance", bucket, "later", forecast_text)
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

def _activities_summary(activities: dict, horizon: str = "today") -> Optional[str]:
    reasons = {a["reason"] for a in activities.values() if a["status"] != "Green"}
    if len(reasons) == 1:
        return reasons.pop()
    statuses = {a["status"] for a in activities.values()}
    if statuses == {"Green"}:
        return "All activities look good tomorrow" if horizon == "tomorrow" else "All activities look good right now"
    return None

def _compute_verdict(flag: dict, plan_status: str, plan_reason: str, situation: dict, wave_ft: float, wind_mph: float) -> dict:
    horizon = situation.get("planning_horizon", "today")
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
        headline, status = ("Not recommended tomorrow", "Red") if horizon == "tomorrow" else ("Not recommended right now", "Red")
        reason = plan_reason
    elif plan_status == "Yellow":
        headline = "Plan with caution tomorrow" if horizon == "tomorrow" else "Go with caution"
        status = "Yellow"
        reason = plan_reason
    elif flag["label"] == "PURPLE FLAG":
        headline, status = "Caution — stinging marine life", "Yellow"
        reason = "Purple flag conditions — check Mote report"
    elif flag["label"] == "YELLOW FLAG":
        headline, status = "Okay with caution", "Yellow"
        reason = f"Moderate surf or wind ({wave_ft:.1f} ft, {wind_mph} mph). {plan_reason}"
    else:
        headline, status = ("Looks good tomorrow", "Green") if horizon == "tomorrow" else ("Good to go", "Green")
        reason = plan_reason

    return {
        "headline": headline,
        "status": status,
        "color": VERDICT_COLORS[status],
        "reason": reason,
    }

def _build_outlook(
    flag: dict,
    wave_ft: float,
    wind_mph: float,
    red_tide: str,
    mote: dict,
    forecast: dict,
    when: str = "today",
) -> dict:
    situation = _analyze_weather_situation(forecast, when=when)
    plan_status, plan_reason = _forecast_plan_status(situation)
    activities = _build_activities(situation, wave_ft, wind_mph, red_tide)
    verdict = _compute_verdict(flag, plan_status, plan_reason, situation, wave_ft, wind_mph)
    official_reason = _get_daily_outlook(wave_ft, wind_mph, red_tide, mote, forecast)["reason"]
    horizon = situation.get("planning_horizon", "today")

    outlook = {
        **flag,
        "reason": official_reason,
        "verdict_title": situation.get("verdict_title", "Today's outlook"),
        "plan_label": situation.get("plan_label", "Plan for today"),
        "planning_horizon": horizon,
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
            "hourly_lines": situation.get("hourly_lines", []),
        },
        "verdict": verdict,
        "activities": activities,
        "activities_summary": _activities_summary(activities, horizon=horizon),
        "storm_badge": len(situation.get("active_alerts", [])) > 0,
        "radar_nearby": situation.get("radar_proximity", {}).get("storm_nearby", False),
        "radar_proximity": situation.get("radar_proximity", {}),
        "active_alerts": situation.get("active_alerts", []),
    }
    if horizon == "tomorrow":
        outlook.pop("water_now", None)
    return outlook

def _has_red_tide(data: dict) -> bool:
    status = _red_tide_status_str(data.get("red_tide", {}))
    return status not in ("Not Present", "Unknown")

def _has_purple_hazard(data: dict) -> bool:
    outlook = data.get("outlook", {})
    if outlook.get("label") == "PURPLE FLAG":
        return True
    jellyfish = str(data.get("mote_extras", {}).get("jellyfish", "None")).lower()
    return jellyfish not in ("none", "n/a", "")

def _outlook_for_when(data: dict, when: str) -> dict:
    if when == "tomorrow":
        return data.get("outlook_tomorrow") or data.get("outlook", {})
    return data.get("outlook", {})

def _rank_tier_level(data: dict, when: str = "today") -> int:
    """Lower level = better rank. 4=avoid, 3=NWS warning, 2=caution, 1=radar, 0=best."""
    if _has_red_tide(data):
        return 4
    outlook = _outlook_for_when(data, when)
    if outlook.get("storm_badge"):
        return 3
    if _has_purple_hazard(data):
        return 2
    if when == "today":
        radar = outlook.get("radar_proximity", {})
        if radar.get("level") == "heavy":
            return 2
        if outlook.get("radar_nearby"):
            return 1
    return 0

def _rank_tier(data: dict, when: str = "today") -> str:
    level = _rank_tier_level(data, when=when)
    if level >= 4:
        return "avoid"
    if level >= 3:
        return "warning"
    if level >= 2:
        return "caution"
    if level >= 1:
        return "radar"
    return "best"

def _rank_sort_key(data: dict, activity: str, when: str = "today") -> tuple:
    """Lower tuple = better rank."""
    outlook = _outlook_for_when(data, when)
    tier_level = _rank_tier_level(data, when=when)
    verdict_status = outlook.get("verdict", {}).get("status")
    activity_status = _activity_status_value(outlook.get("activities", {}), activity)
    status_score = ACTIVITY_RANK.get(verdict_status or activity_status, 2)
    wind = data.get("weather", {}).get("wind_mph", 99)
    surf = data.get("surf", {}).get("height", 99)
    if when == "tomorrow":
        surf = data.get("surf", {}).get("tomorrow_height", surf)
    radar_dbz = outlook.get("radar_proximity", {}).get("max_dbz", 0) if when == "today" else 0
    return (tier_level, status_score, wind, surf, -radar_dbz)

def _rank_summary(data: dict, activity: str, when: str = "today") -> str:
    outlook = _outlook_for_when(data, when)
    parts = [
        f"{activity.title()}: {_activity_status_value(outlook.get('activities', {}), activity)}",
        f"{data.get('weather', {}).get('wind_mph', '--')} mph wind",
    ]
    if when == "tomorrow":
        parts.append(f"{data.get('surf', {}).get('tomorrow_height', data.get('surf', {}).get('height', '--'))} ft surf (forecast)")
    else:
        parts.append(f"{data.get('surf', {}).get('height', '--')} ft surf")
    red_tide = _red_tide_status_str(data.get("red_tide", {}))
    if red_tide == "Unknown":
        parts.append("red tide data unavailable")
    elif red_tide != "Not Present":
        parts.append(f"red tide ({red_tide})")
    if _has_purple_hazard(data):
        parts.append("purple flag / stinging life")
    if outlook.get("storm_badge"):
        parts.append("NWS weather warning")
    elif when == "today" and outlook.get("radar_nearby"):
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
    when: str = "today",
    coast: str = "all",
    dog_friendly: bool = False,
    free_parking: bool = False,
) -> dict:
    activity = activity if activity in VALID_ACTIVITIES else "paddling"
    limit = max(1, min(limit, len(BEACH_CONFIG)))
    anchor = _resolve_rank_anchor(beach_id=beach_id, near_lat=near_lat, near_lon=near_lon)
    use_nearby = anchor is not None
    requested_radius = radius_miles if radius_miles is not None else DEFAULT_NEARBY_RADIUS_MILES
    active_radius = requested_radius if use_nearby else None
    radius_expanded = False

    def _passes_filters(candidate_id: str, config: dict) -> bool:
        if coast != "all" and config.get("coast") != coast:
            return False
        amenities = BEACH_AMENITIES.get(candidate_id, {})
        if dog_friendly and not amenities.get("dog_friendly"):
            return False
        if free_parking and amenities.get("parking") != "free":
            return False
        return True

    candidates = []
    for candidate_id, config in BEACH_CONFIG.items():
        if not _passes_filters(candidate_id, config):
            continue
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
            if not _passes_filters(candidate_id, config):
                continue
            data = GLOBAL_DATA_STORE.get(candidate_id)
            if not data or data.get("error"):
                continue
            dist = distance_miles(anchor["lat"], anchor["lon"], config["lat"], config["lon"])
            if dist <= active_radius:
                candidates.append((candidate_id, config, data, dist))

    candidates.sort(key=lambda item: _rank_sort_key(item[2], activity, when=when))
    results = []
    for idx, (candidate_id, config, data, dist) in enumerate(candidates[:limit], start=1):
        outlook = _outlook_for_when(data, when)
        surf_ft = data.get("surf", {}).get("height")
        if when == "tomorrow":
            surf_ft = data.get("surf", {}).get("tomorrow_height", surf_ft)
        entry = {
            "rank": idx,
            "beach_id": candidate_id,
            "name": config["name"],
            "rank_tier": _rank_tier(data, when=when),
            "activity_status": _activity_status_value(outlook.get("activities", {}), activity),
            "flag": data.get("outlook", {}).get("label", "UNKNOWN"),
            "wind_mph": data.get("weather", {}).get("wind_mph"),
            "surf_ft": surf_ft,
            "red_tide": data.get("red_tide", {}).get("status", "Not Present"),
            "jellyfish": data.get("mote_extras", {}).get("jellyfish", "None"),
            "summary": _rank_summary(data, activity, when=when),
            "amenities": BEACH_AMENITIES.get(candidate_id),
        }
        if dist is not None:
            entry["distance_miles"] = round(dist, 1)
        results.append(entry)

    response = {
        "activity": activity,
        "when": when,
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
def _extract_mote_parameters(report: dict) -> dict:
    params = {}
    for category in report.get("beachReport", []) or []:
        for rp in category.get("reportParameters", []) or []:
            name = (rp.get("parameter") or {}).get("name")
            if not name:
                continue
            params[name] = rp.get("display") or rp.get("value") or "Unknown"
    return params


def _normalize_mote_report(params: dict, *, source_url: str, beach_name: str = "") -> dict:
    water_color = params.get("Water Color", "Unknown")
    if str(water_color).lower() == "clear":
        water = "Clear Water"
    else:
        water = water_color
    drift_algae = str(params.get("Drift Algae", "None"))
    algae = "No Algae Observed" if drift_algae.lower() == "none" else "Algae Present"
    meta = _source_meta(True, source_url)
    if beach_name:
        meta["beach_name"] = beach_name
    return {
        "intensity": params.get("Surf Intensity", "Unknown"),
        "type": params.get("Surf Type", "Unknown"),
        "water": water,
        "algae": algae,
        "algae_type": params.get("Drift Algae Type", "N/A"),
        "jellyfish": params.get("Jellyfish", "None"),
        "meta": meta,
    }


def _get_mote_report(config: dict) -> dict:
    try:
        r = requests.post(
            MOTE_GQL_URL,
            json={"query": MOTE_BEACH_QUERY, "variables": {"id": str(config["mote_id"])}},
            headers={"Content-Type": "application/json", "User-Agent": "MarineAgent/1.0"},
            timeout=8,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("errors"):
            raise ValueError(payload["errors"][0].get("message", "graphql error"))
        beach = payload.get("data", {}).get("beach")
        reports = (beach or {}).get("lastThreeDaysOfReports") or []
        if not beach or not reports:
            raise ValueError("no recent beach report")
        return _normalize_mote_report(
            _extract_mote_parameters(reports[0]),
            source_url=MOTE_GQL_URL,
            beach_name=beach.get("name", ""),
        )
    except Exception as exc:
        return {
            "intensity": "Unknown",
            "type": "Unknown",
            "water": "Unknown",
            "algae": "Unknown",
            "algae_type": "N/A",
            "jellyfish": "Unknown",
            "meta": _source_meta(False, MOTE_GQL_URL, str(exc)[:120]),
        }


def _map_hab_concentration(concentration: Optional[str], density: Optional[int]) -> str:
    label = (concentration or "").strip().lower()
    if "not present" in label or "background" in label:
        return "Not Present"
    if "very low" in label:
        return "Low"
    if re.search(r"\blow\b", label):
        return "Low"
    if "medium" in label or "high" in label:
        return "Medium/High"
    if "testing not performed" in label:
        return "Unknown"
    if density is not None:
        if density > 100000:
            return "Medium/High"
        if density > 10000:
            return "Low"
        if density >= 0:
            return "Not Present"
    return "Unknown"


def _get_red_tide_status(config: dict) -> dict:
    params = {
        "geometry": f"{config['lon']},{config['lat']}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "distance": 100,
        "units": "esriSRUnit_Kilometer",
        "outFields": "Site,Concentrations,DensityPerLiter,Collection_Date,Latitude,Longitude",
        "orderByFields": "Collection_Date DESC",
        "resultRecordCount": 5,
        "f": "json",
    }
    try:
        r = requests.get(FWC_HAB_URL, params=params, timeout=8).json()
        if r.get("error"):
            raise ValueError(r["error"].get("message", "hab query failed"))
        features = r.get("features", [])
        for feat in features:
            attrs = feat.get("attributes", {})
            status = _map_hab_concentration(
                attrs.get("Concentrations"),
                attrs.get("DensityPerLiter"),
            )
            if status != "Unknown":
                meta = _source_meta(True, FWC_HAB_URL)
                meta["site"] = attrs.get("Site")
                meta["concentration"] = attrs.get("Concentrations")
                return {"status": status, "meta": meta}
        meta = _source_meta(True, FWC_HAB_URL)
        meta["note"] = "No FWC samples within 100 km in the current 8-day map window"
        return {"status": "Not Present", "meta": meta}
    except Exception as exc:
        return {
            "status": "Unknown",
            "meta": _source_meta(False, FWC_HAB_URL, str(exc)[:120]),
        }

def _describe_wave_period(period: Optional[float]) -> str:
    if period is None or period <= 0:
        return ""
    p = round(period, 1)
    if p < 6:
        return (
            f"{p} sec between wave crests — short-period chop from nearby wind, "
            "not long rolling swell"
        )
    if p < 9:
        return f"{p} sec between wave crests — moderately spaced, somewhat organized waves"
    if p < 13:
        return f"{p} sec between wave crests — longer-period swell, cleaner and more powerful"
    return f"{p} sec between wave crests — long ground swell with more energy per wave"

def _get_marine_day_stats(config: dict, target_date: datetime.date) -> tuple[float, float]:
    try:
        url = (
            f"https://marine-api.open-meteo.com/v1/marine?latitude={config['lat']}&longitude={config['lon']}"
            "&hourly=wave_height,swell_wave_period,sea_surface_temperature&timezone=auto"
        )
        r = requests.get(url, timeout=5).json()
        times = r["hourly"]["time"]
        waves = r["hourly"]["wave_height"]
        periods = r["hourly"]["swell_wave_period"]
        wave_vals = []
        period_vals = []
        for idx, stamp in enumerate(times):
            start = datetime.datetime.fromisoformat(stamp)
            if start.tzinfo is None:
                start = start.replace(tzinfo=FL_TZ)
            else:
                start = start.astimezone(FL_TZ)
            if start.date() != target_date or not (8 <= start.hour <= 18):
                continue
            if waves[idx] is not None:
                wave_vals.append(waves[idx] * 3.28)
            if periods[idx] is not None:
                period_vals.append(periods[idx])
        wave_ft = sum(wave_vals) / len(wave_vals) if wave_vals else 0.5
        period = sum(period_vals) / len(period_vals) if period_vals else 4.0
        return wave_ft, period
    except Exception:
        return 0.5, 4.0

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

def _wind_dir_from_deg(wind_deg: Optional[float]) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round((wind_deg or 0) / 45) % 8]


def _parse_nws_wind_mph(wind_text: Optional[str]) -> Optional[float]:
    if not wind_text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", wind_text)
    return round(float(match.group(1)), 1) if match else None


def _get_open_meteo_weather(config: dict) -> Optional[dict]:
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={config['lat']}&longitude={config['lon']}"
        "&current=temperature_2m,wind_speed_10m,wind_direction_10m"
        "&wind_speed_unit=mph&temperature_unit=fahrenheit"
    )
    try:
        r = requests.get(url, timeout=5).json()
        current = r.get("current", {})
        temp_f = current.get("temperature_2m")
        wind_mph = current.get("wind_speed_10m")
        wind_deg = current.get("wind_direction_10m")
        if temp_f is None or wind_mph is None:
            return None
        return {
            "temp_f": round(float(temp_f), 1),
            "wind_mph": round(float(wind_mph), 1),
            "wind_dir": _wind_dir_from_deg(wind_deg),
            "meta": _source_meta(True, url),
        }
    except Exception:
        return None


def _get_nws_hourly_weather(config: dict) -> Optional[dict]:
    points_url = f"https://api.weather.gov/points/{config['lat']},{config['lon']}"
    try:
        points_r = requests.get(points_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        hourly_url = points_r.get('properties', {}).get('forecastHourly')
        if not hourly_url:
            return None
        h_r = requests.get(hourly_url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=8).json()
        period = h_r.get('properties', {}).get('periods', [{}])[0]
        temp_f = period.get('temperature')
        wind_mph = _parse_nws_wind_mph(period.get('windSpeed'))
        wind_dir = period.get('windDirection')
        if temp_f is None or wind_mph is None or not wind_dir:
            return None
        return {
            "temp_f": round(float(temp_f), 1),
            "wind_mph": wind_mph,
            "wind_dir": wind_dir,
            "meta": _source_meta(True, hourly_url),
        }
    except Exception:
        return None


def _merge_weather_obs(primary: dict, fallback: dict, *, fallback_name: str, station_url: str) -> dict:
    merged = {
        "temp_f": primary.get("temp_f") if primary.get("temp_f") is not None else fallback.get("temp_f"),
        "wind_mph": primary.get("wind_mph") if primary.get("wind_mph") is not None else fallback.get("wind_mph"),
        "wind_dir": primary.get("wind_dir") if primary.get("wind_dir") not in (None, "N/A") else fallback.get("wind_dir"),
    }
    if merged["temp_f"] is None or merged["wind_mph"] is None:
        return primary
    meta = fallback.get("meta", _source_meta(True, station_url)).copy()
    meta["fallback"] = fallback_name
    meta["note"] = f"NWS station observation incomplete; filled from {fallback_name}"
    meta["station_url"] = station_url
    merged["meta"] = meta
    return merged


def _get_nws_obs(config: dict) -> dict:
    url = f"https://api.weather.gov/stations/{config['nws_station']}/observations/latest"
    partial = {
        "temp_f": None,
        "wind_mph": None,
        "wind_dir": "N/A",
    }
    try:
        r = requests.get(url, headers={'User-Agent': 'MarineAgent/1.0'}, timeout=5).json()
        p = r.get('properties', {})
        raw_temp = p.get('temperature', {}).get('value')
        partial["temp_f"] = round((raw_temp * 9/5) + 32, 1) if raw_temp is not None else None
        raw_wind = p.get('windSpeed', {}).get('value')
        partial["wind_mph"] = round(raw_wind / 1.6, 1) if raw_wind is not None else None
        wind_deg = p.get('windDirection', {}).get('value')
        if wind_deg is not None:
            partial["wind_dir"] = _wind_dir_from_deg(wind_deg)
        if partial["temp_f"] is not None and partial["wind_mph"] is not None:
            return {
                **partial,
                "meta": _source_meta(True, url),
            }
    except Exception:
        pass

    hourly = _get_nws_hourly_weather(config)
    if hourly:
        merged = _merge_weather_obs(partial, hourly, fallback_name="nws_hourly", station_url=url)
        if merged.get("temp_f") is not None and merged.get("wind_mph") is not None:
            return merged

    open_meteo = _get_open_meteo_weather(config)
    if open_meteo:
        merged = _merge_weather_obs(partial, open_meteo, fallback_name="open_meteo", station_url=url)
        if merged.get("temp_f") is not None and merged.get("wind_mph") is not None:
            return merged

    return {
        "temp_f": None,
        "wind_mph": None,
        "wind_dir": "N/A",
        "meta": _source_meta(False, url, "incomplete observation"),
    }

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
            "meta": _source_meta(True, points_url),
        }
    except Exception as exc:
        points_url = f"https://api.weather.gov/points/{config['lat']},{config['lon']}"
        return {
            "summary": "Forecast unavailable — check weather.gov.",
            "rip_current": "Unknown",
            "source": "NWS",
            "periods": [],
            "hourly_periods": [],
            "hazards": _empty_hazards(),
            "active_alerts": [],
            "meta": _source_meta(False, points_url, str(exc)[:120]),
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
    tide_source = f"https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    fallback = {
        "predictions": [],
        "water_temp": water_temp,
        "water_temp_source": water_temp_source,
        "current_status": "N/A",
        "trend": "N/A",
        "next_event": "Tides Unavailable",
        "source": f"NOAA {config['tide_id']} ({dist})",
        "meta": _source_meta(False, tide_source, "tide predictions unavailable"),
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
            "meta": _source_meta(True, tide_source),
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
    if red_tide == "Unknown":
        return {
            "label": "YELLOW FLAG",
            "vibe": "Data Incomplete",
            "color": "#facc15",
            "reason": "Red tide data unavailable — check FWC before entering the water.",
        }
    if red_tide == "Medium/High" or wave_ft > 6.0:
        return {"label": "DOUBLE RED", "vibe": "Water Closed", "color": "#7f1d1d", "reason": f"High hazard surge or biological risk. {timing}"}
    if wave_ft > 4.0 or wind_mph > 25 or red_tide not in ("Not Present", "Unknown"):
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
        obs = _get_nws_obs(config)
        temp_f = obs["temp_f"] if obs.get("temp_f") is not None else 75.0
        wind_mph = obs["wind_mph"] if obs.get("wind_mph") is not None else 15.0
        wind_dir = obs.get("wind_dir", "N/A")
        mote = _get_mote_report(config)
        red_tide = _get_red_tide_status(config)
        red_tide_status = _red_tide_status_str(red_tide)
        forecast = _get_nws_forecast(config)
        forecast["radar_proximity"] = _get_radar_proximity(config["lat"], config["lon"])
        tides = _get_tide_data(config, modeled_sst_f=sst_f)
        jellyfish = str(mote.get("jellyfish", "None")).lower()
        jellyfish_present = jellyfish not in ("none", "n/a", "unknown", "")

        flag = calculate_flag(wave_ft, wind_mph, red_tide_status, jellyfish_present)
        tomorrow_date = _fl_now().date() + datetime.timedelta(days=1)
        tomorrow_wave_ft, tomorrow_period = _get_marine_day_stats(config, tomorrow_date)

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
                "tomorrow_height": round(tomorrow_wave_ft, 1),
                "period": round(period, 1) if period else None,
                "tomorrow_period": round(tomorrow_period, 1),
                "period_note": _describe_wave_period(period),
                "intensity": mote["intensity"],
                "type": mote["type"],
                "rip_current": forecast["rip_current"],
            },
            "weather": obs,
            "red_tide": red_tide,
            "mote_extras": mote,
            "outlook": _build_outlook(flag, wave_ft, wind_mph, red_tide_status, mote, forecast, when="today"),
            "outlook_tomorrow": _build_outlook(
                flag, tomorrow_wave_ft, wind_mph, red_tide_status, mote, forecast, when="tomorrow"
            ),
            "teeth": _compute_shark_teeth_score(config, wave_ft, tides, mote),
            "clarity": {"label": "Good" if wave_ft < 1.5 else "Fair", "feet": round(max(1, 15 - (wave_ft * 4)), 0)}
        }
        return _store_beach_data(beach_id, data)
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
    print("[STARTUP] Hydrating beach cache from Redis...")
    try:
        loaded = await asyncio.to_thread(cache_store.load_all, list(BEACH_CONFIG.keys()))
        for beach_id, data in loaded.items():
            data["data_quality"] = _build_data_quality(data, from_redis=True)
            GLOBAL_DATA_STORE[beach_id] = data
        if loaded:
            print(f"[STARTUP] Redis hydrated {len(loaded)} beaches")
    except Exception as e:
        print(f"[WARN] redis hydrate failed (non-fatal): {str(e)[:80]}")

    missing = [bid for bid in BEACH_CONFIG if bid not in GLOBAL_DATA_STORE]
    if missing:
        print(f"[STARTUP] Refreshing {len(missing)} beaches not in Redis...")
    for beach_id in missing:
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
    cached = GLOBAL_DATA_STORE.get(beach_id)
    if cached and not cached.get("error") and _cache_age_seconds(cached) <= DATA_STALE_SECONDS:
        cached["data_quality"] = _build_data_quality(cached)
        return cached
    return refresh_one_beach(beach_id)

@mcp.tool()
def rank_beaches(
    activity: str = "paddling",
    limit: int = 5,
    beach_id: str = "venice",
    radius_miles: int = 50,
    when: str = "today",
) -> dict:
    """Rank beaches for an activity near an anchor beach (default 50mi). Supports when=today or when=tomorrow."""
    return rank_beaches_data(
        activity=activity,
        limit=limit,
        beach_id=beach_id,
        radius_miles=radius_miles,
        when=when,
    )

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
        cached["data_quality"] = _build_data_quality(cached)
        data = cached
    else:
        data = await asyncio.to_thread(refresh_one_beach, beach_id)
    # Beach Pulse: additive, never breaks this response (build_beach_pulse swallows errors).
    reports_on = BEACH_CONFIG.get(beach_id, {}).get("reports_enabled", False)
    data["beach_pulse"] = await asyncio.to_thread(reports.build_beach_pulse, beach_id, reports_on)
    data["amenities"] = BEACH_AMENITIES.get(beach_id)
    return data

# --- BEACH PULSE (community reports) ROUTES ---
class ReportIn(BaseModel):
    beach_id: str
    report_type: str
    notes: Optional[str] = None
    beach_lat: Optional[float] = None
    beach_lng: Optional[float] = None

async def require_reporter(authorization: Optional[str] = Header(default=None)) -> str:
    """Verify the Supabase Bearer JWT and return the reporter's user id. 401 on failure.
    Transport-agnostic: a native client sends the same header (see handoff §0/§3c)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return await asyncio.to_thread(reports.verify_jwt, token)
    except reports.ReportAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

@app.post("/api/reports")
async def create_report(body: ReportIn, reporter_id: str = Depends(require_reporter)):
    if body.beach_id not in BEACH_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown beach_id: {body.beach_id}")
    if not BEACH_CONFIG[body.beach_id].get("reports_enabled", False):
        raise HTTPException(status_code=403, detail="reports not enabled for this beach")
    try:
        created = await asyncio.to_thread(
            reports.submit_report,
            reporter_id, body.beach_id, body.report_type,
            body.notes, body.beach_lat, body.beach_lng,
        )
    except reports.ReportError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return {"report": created}

@app.delete("/api/reports/{report_id}", status_code=204)
async def undo_report(report_id: str, reporter_id: str = Depends(require_reporter)):
    try:
        await asyncio.to_thread(reports.delete_own_report, reporter_id, report_id)
    except reports.ReportError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return Response(status_code=204)

@app.get("/api/reports/{beach_id}")
async def list_reports(beach_id: str):
    if beach_id not in BEACH_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown beach_id: {beach_id}")
    rows = await asyncio.to_thread(reports.get_reports_for_beach, beach_id)
    return {"beach_id": beach_id, "reports": rows}

@app.get("/api/me/reports")
async def my_reports(reporter_id: str = Depends(require_reporter)):
    rows = await asyncio.to_thread(reports.get_reports_for_user, reporter_id)
    return {"reports": rows}

@app.delete("/api/me", status_code=204)
async def delete_me(reporter_id: str = Depends(require_reporter)):
    try:
        await asyncio.to_thread(reports.delete_account, reporter_id)
    except reports.ReportError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return Response(status_code=204)

@app.get("/api/me/favorites")
async def my_favorites(reporter_id: str = Depends(require_reporter)):
    favs = await asyncio.to_thread(reports.get_favorites, reporter_id)
    return {"favorites": favs}

@app.post("/api/me/favorites", status_code=204)
async def add_my_favorite(body: dict, reporter_id: str = Depends(require_reporter)):
    beach_id = (body or {}).get("beach_id", "")
    if beach_id not in BEACH_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown beach_id: {beach_id}")
    try:
        await asyncio.to_thread(reports.add_favorite, reporter_id, beach_id)
    except reports.ReportError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return Response(status_code=204)

@app.delete("/api/me/favorites/{beach_id}", status_code=204)
async def remove_my_favorite(beach_id: str, reporter_id: str = Depends(require_reporter)):
    if beach_id not in BEACH_CONFIG:
        raise HTTPException(status_code=400, detail=f"Unknown beach_id: {beach_id}")
    try:
        await asyncio.to_thread(reports.remove_favorite, reporter_id, beach_id)
    except reports.ReportError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    return Response(status_code=204)

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
    dog_friendly: bool = False,
    free_parking: bool = False,
):
    if when not in ("today", "tomorrow"):
        raise HTTPException(status_code=400, detail="when must be 'today' or 'tomorrow'")
    if activity not in VALID_ACTIVITIES:
        raise HTTPException(status_code=400, detail=f"activity must be one of: {', '.join(sorted(VALID_ACTIVITIES))}")
    if coast not in ("all", "gulf", "atlantic"):
        raise HTTPException(status_code=400, detail="coast must be 'all', 'gulf', or 'atlantic'")
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
        when=when,
        coast=coast,
        dog_friendly=dog_friendly,
        free_parking=free_parking,
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
        "redis": cache_store.status(),
        "disclaimer": SAFETY_DISCLAIMER,
    }

print("[STARTUP] FastAPI app created and ready - all beach data sources integrated")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[STARTUP] Starting uvicorn on 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
