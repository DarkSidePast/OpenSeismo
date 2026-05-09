import os
import sys
import math
import time
import json
import random
import logging
import threading
import webbrowser
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, request, render_template

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seismic_tracker")

def resource_path(relative_path: str) -> str:
    """
    Works both in normal Python and PyInstaller onefile mode.
    """
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

app = Flask(
    __name__,
    template_folder=resource_path("templates"),
    static_folder=resource_path("static"),
)

USGS_ALL_DAY = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
USGS_SIGNIFICANT_MONTH = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson"

_cache = {
    "earthquakes": None,
    "earthquakes_time": None,
}

RISK_ORDER = {"low": 1, "moderate": 2, "high": 3, "very high": 4, "extreme": 5}

SAFETY_ACTIONS = {
    "earthquake": [
        "Drop, cover, and hold on during shaking.",
        "Move away from glass, shelves, chimneys, and exterior walls.",
        "After shaking, check for gas leaks, damaged wiring, and unstable structures.",
    ],
    "tsunami": [
        "If shaking is long or strong near the coast, move inland or to high ground immediately.",
        "Do not wait for an official alert if natural warning signs are present.",
        "Stay away from beaches and river mouths until authorities clear the area.",
    ],
    "volcano": [
        "Follow exclusion zones and avoid valleys downstream from active volcanoes.",
        "Use eye and breathing protection during ashfall.",
        "Keep water, masks, radios, and vehicle filters protected from ash.",
    ],
    "landslide": [
        "Avoid steep slopes, recent burn scars, and saturated hillsides during heavy rain.",
        "Leave immediately if you hear cracking trees, see new ground cracks, or notice sudden muddy water.",
        "Use routes away from gullies and debris-flow channels.",
    ],
    "flood": [
        "Move to higher ground and avoid underpasses, dry washes, and low bridges.",
        "Never drive through floodwater.",
        "Keep evacuation documents and medications ready during flood watches.",
    ],
    "wildfire": [
        "Prepare to leave early when wind, heat, and fire weather align.",
        "Keep phones charged and know at least two evacuation routes.",
        "Close windows and use filtered indoor air when smoke is heavy.",
    ],
    "cyclone": [
        "Secure loose outdoor objects before winds arrive.",
        "Move away from coastlines and flood-prone areas if evacuation orders are issued.",
        "Shelter in an interior room away from windows during peak winds.",
    ],
}

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def fetch_json(url, timeout=12):
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "SeismicDisasterTracker/1.0"})
    r.raise_for_status()
    return r.json()

def get_earthquakes(filter_magnitude=0.0):
    global _cache
    fresh = (
        _cache["earthquakes"] is not None
        and _cache["earthquakes_time"] is not None
        and datetime.now(timezone.utc) - _cache["earthquakes_time"] < timedelta(minutes=4)
    )

    if fresh:
        data = _cache["earthquakes"]
    else:
        try:
            data = fetch_json(USGS_ALL_DAY)
            _cache["earthquakes"] = data
            _cache["earthquakes_time"] = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning("USGS fetch failed: %s", e)
            data = _cache["earthquakes"] or {"type": "FeatureCollection", "features": []}

    features = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        mag = props.get("mag")
        if mag is None:
            continue
        if float(mag) >= filter_magnitude:
            enriched = dict(feature)
            enriched_props = dict(props)
            coords = feature.get("geometry", {}).get("coordinates", [0, 0, 10])
            enriched_props["risk_assessment"] = classify_earthquake(enriched_props, coords)
            enriched["properties"] = enriched_props
            features.append(enriched)

    return {
        "type": "FeatureCollection",
        "features": features,
        "count": len(features),
        "source": "USGS all_day GeoJSON",
        "last_updated_utc": _cache["earthquakes_time"].isoformat() if _cache["earthquakes_time"] else None,
    }

def get_volcanoes():
    return [
        {"name": "Mount Etna", "lat": 37.7510, "lon": 14.9934, "status": "active", "region": "Sicily, Italy", "elevation": 3329},
        {"name": "Stromboli", "lat": 38.789, "lon": 15.213, "status": "active", "region": "Italy", "elevation": 924},
        {"name": "Vesuvius", "lat": 40.8212, "lon": 14.4264, "status": "dormant", "region": "Italy", "elevation": 1281},
        {"name": "Santorini", "lat": 36.404, "lon": 25.396, "status": "active caldera", "region": "Greece", "elevation": 367},
        {"name": "Mount Fuji", "lat": 35.3606, "lon": 138.7274, "status": "dormant", "region": "Japan", "elevation": 3776},
        {"name": "Sakurajima", "lat": 31.5933, "lon": 130.6569, "status": "active", "region": "Japan", "elevation": 1117},
        {"name": "Aso", "lat": 32.884, "lon": 131.104, "status": "active", "region": "Japan", "elevation": 1592},
        {"name": "Merapi", "lat": -7.5410, "lon": 110.4420, "status": "active", "region": "Indonesia", "elevation": 2968},
        {"name": "Krakatoa / Anak Krakatau", "lat": -6.102, "lon": 105.423, "status": "active", "region": "Indonesia", "elevation": 813},
        {"name": "Taal", "lat": 14.002, "lon": 120.993, "status": "active", "region": "Philippines", "elevation": 311},
        {"name": "Mayon", "lat": 13.257, "lon": 123.685, "status": "active", "region": "Philippines", "elevation": 2463},
        {"name": "Kilauea", "lat": 19.421, "lon": -155.287, "status": "active", "region": "Hawaii, USA", "elevation": 1247},
        {"name": "Mauna Loa", "lat": 19.475, "lon": -155.608, "status": "active", "region": "Hawaii, USA", "elevation": 4169},
        {"name": "Mount St. Helens", "lat": 46.2011, "lon": -122.1811, "status": "active/dormant", "region": "USA", "elevation": 2549},
        {"name": "Popocatépetl", "lat": 19.023, "lon": -98.622, "status": "active", "region": "Mexico", "elevation": 5426},
        {"name": "Nevado del Ruiz", "lat": 4.892, "lon": -75.324, "status": "active", "region": "Colombia", "elevation": 5321},
        {"name": "Villarrica", "lat": -39.42, "lon": -71.93, "status": "active", "region": "Chile", "elevation": 2847},
        {"name": "Yellowstone", "lat": 44.428, "lon": -110.588, "status": "caldera", "region": "USA", "elevation": 2805},
    ]

def get_faults():
    return [
        {
            "name": "San Andreas Fault",
            "type": "transform",
            "risk_level": "extreme",
            "classification": "major plate-boundary strike-slip fault",
            "primary_hazards": ["violent shaking", "surface rupture", "urban infrastructure disruption"],
            "exposure": "Dense California population centers and lifeline corridors.",
            "watch": "Elevated concern after nearby M5+ sequences or long-period regional strain changes.",
            "preparedness": "Secure heavy furniture, retrofit soft-story buildings, and maintain 14 days of water.",
            "points": [[42.0, -120.5], [40.0, -121.5], [38.0, -122.0], [36.0, -120.5], [35.0, -119.0], [34.0, -117.5], [33.0, -116.2]],
        },
        {
            "name": "Japan Trench",
            "type": "subduction",
            "risk_level": "extreme",
            "classification": "megathrust subduction interface",
            "primary_hazards": ["great earthquakes", "tsunami", "coastal subsidence"],
            "exposure": "Pacific-facing Honshu, ports, power, and rail corridors.",
            "watch": "Tsunami-capable after strong offshore thrust events, especially shallow M7+.",
            "preparedness": "Know vertical evacuation sites and move immediately after long or strong shaking.",
            "points": [[45.0, 151.0], [42.0, 149.0], [38.0, 147.0], [35.0, 145.0], [32.0, 143.0], [29.0, 141.5]],
        },
        {
            "name": "Nankai Trough",
            "type": "subduction",
            "risk_level": "extreme",
            "classification": "locked megathrust segment",
            "primary_hazards": ["great earthquakes", "tsunami", "liquefaction"],
            "exposure": "Tokai, Kii, Shikoku, Kyushu, and Pacific industrial belts.",
            "watch": "Multi-segment rupture risk is the dominant safety concern.",
            "preparedness": "Review coastal evacuation routes and brace utilities before shaking starts.",
            "points": [[34.8, 138.5], [33.8, 136.8], [32.9, 134.2], [31.7, 132.0], [30.5, 130.4]],
        },
        {
            "name": "Alpine-Himalayan Belt",
            "type": "collision",
            "risk_level": "high",
            "classification": "continental collision belt",
            "primary_hazards": ["crustal earthquakes", "landslides", "dammed rivers"],
            "exposure": "Mountain communities, roads, hydropower, and long valleys.",
            "watch": "Landslide danger rises sharply after strong shaking or intense rain.",
            "preparedness": "Avoid unstable slopes after earthquakes and keep alternate road routes planned.",
            "points": [[36, 5], [38, 15], [39, 25], [38, 35], [37, 45], [36, 55], [35, 65], [32, 75], [29, 85], [27, 95]],
        },
        {
            "name": "Anatolian Fault System",
            "type": "transform",
            "risk_level": "high",
            "classification": "continental strike-slip system",
            "primary_hazards": ["strong shaking", "surface rupture", "cascading urban damage"],
            "exposure": "Northern Turkey, Marmara region, and critical transport corridors.",
            "watch": "Aftershock sequences can keep damaged buildings unsafe for days to weeks.",
            "preparedness": "Do not re-enter cracked buildings until inspected; plan family reunification points.",
            "points": [[40.8, 26.0], [40.7, 29.0], [40.5, 32.0], [40.0, 35.5], [39.4, 39.5], [39.0, 42.0]],
        },
        {
            "name": "Caucasus Collision Zone",
            "type": "collision",
            "risk_level": "moderate",
            "classification": "active continental collision and thrusting",
            "primary_hazards": ["moderate crustal earthquakes", "rockfall", "localized landslides"],
            "exposure": "Georgia, Armenia, Azerbaijan, and trans-Caucasus corridors.",
            "watch": "Slope failure risk can rise after shaking, snowmelt, or prolonged rain.",
            "preparedness": "Keep emergency kits in vehicles and avoid canyon roads after noticeable shaking.",
            "points": [[40.0, 40.0], [41.0, 42.0], [42.0, 44.0], [42.5, 46.0], [42.0, 48.0], [41.5, 50.0]],
        },
        {
            "name": "Chile-Peru Trench",
            "type": "subduction",
            "risk_level": "extreme",
            "classification": "fast-converging megathrust",
            "primary_hazards": ["great earthquakes", "tsunami", "coastal uplift/subsidence"],
            "exposure": "Long coastal settlements, mines, ports, and Pan-American corridors.",
            "watch": "Shallow offshore M7+ events require immediate tsunami awareness.",
            "preparedness": "Follow coastal evacuation signage and maintain shoes/flashlight near beds.",
            "points": [[5, -82], [-5, -80], [-15, -77], [-25, -73], [-35, -73], [-45, -75], [-55, -76]],
        },
        {
            "name": "Mid-Atlantic Ridge",
            "type": "divergent",
            "risk_level": "moderate",
            "classification": "oceanic spreading ridge",
            "primary_hazards": ["moderate earthquakes", "submarine volcanism", "localized tsunami"],
            "exposure": "Mostly offshore, with Iceland and Atlantic islands most exposed.",
            "watch": "Volcanic unrest and earthquake swarms are more relevant than single large ruptures.",
            "preparedness": "In volcanic zones, follow gas, fissure, and lava-flow exclusion notices.",
            "points": [[70, -20], [55, -30], [40, -38], [25, -43], [10, -38], [-5, -30], [-20, -18], [-35, -15], [-50, -20]],
        },
        {
            "name": "New Zealand Alpine Fault",
            "type": "transform/oblique",
            "risk_level": "high",
            "classification": "oblique plate-boundary fault",
            "primary_hazards": ["severe shaking", "landslides", "river blockage"],
            "exposure": "South Island communities, alpine roads, and tourism routes.",
            "watch": "Landslide and isolation risk can exceed direct shaking risk in mountain districts.",
            "preparedness": "Carry vehicle supplies and expect road closures after strong shaking.",
            "points": [[-41.0, 173.5], [-42.5, 171.8], [-44.0, 170.0], [-45.2, 168.8], [-46.0, 167.5]],
        },
        {
            "name": "Sumatra Megathrust",
            "type": "subduction",
            "risk_level": "extreme",
            "classification": "tsunami-genic megathrust",
            "primary_hazards": ["great earthquakes", "tsunami", "coastal liquefaction"],
            "exposure": "Western Sumatra, island communities, ports, and low coastal plains.",
            "watch": "Strong offshore shaking is a natural tsunami warning.",
            "preparedness": "Move to high ground immediately after long shaking; keep routes practiced.",
            "points": [[6, 94], [2, 95], [-2, 97], [-6, 101], [-9, 105]],
        },
        {
            "name": "Cascadia Subduction Zone",
            "type": "subduction",
            "risk_level": "extreme",
            "classification": "locked megathrust and forearc fault network",
            "primary_hazards": ["great earthquakes", "tsunami", "liquefaction", "long outages"],
            "exposure": "Pacific Northwest coast, Seattle, Portland, Vancouver Island, and coastal lifelines.",
            "watch": "Long coastal shaking means evacuate uphill before official confirmation.",
            "preparedness": "Plan two-week self-sufficiency and mapped tsunami evacuation on foot.",
            "points": [[50.0, -128.5], [48.5, -126.5], [46.5, -125.0], [44.5, -124.4], [42.0, -124.2], [40.5, -124.0]],
        },
        {
            "name": "Hellenic Arc",
            "type": "subduction",
            "risk_level": "high",
            "classification": "Mediterranean subduction arc",
            "primary_hazards": ["strong earthquakes", "tsunami", "landslides"],
            "exposure": "Crete, Dodecanese, western Turkey, and dense coastal tourism corridors.",
            "watch": "Coastal basins can amplify shaking and tsunami runup locally.",
            "preparedness": "Keep evacuation plans visible in hotels, ports, and ferry terminals.",
            "points": [[36.8, 20.5], [35.8, 22.5], [35.2, 24.5], [35.3, 26.5], [36.0, 28.5]],
        },
    ]

def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1-a))

def risk_score(level):
    return RISK_ORDER.get(str(level).lower(), 0)

def classify_earthquake(props, coords):
    mag = float(props.get("mag") or 0)
    depth = coords[2] if len(coords) > 2 and coords[2] is not None else 10
    alert = (props.get("alert") or "").lower()
    tsunami = int(props.get("tsunami") or 0)
    felt = int(props.get("felt") or 0)
    score = mag * 12
    if depth <= 35:
        score += 12
    if tsunami:
        score += 18
    if alert == "yellow":
        score += 10
    elif alert == "orange":
        score += 20
    elif alert == "red":
        score += 32
    score += min(12, felt / 40)

    if score >= 92:
        level = "extreme"
    elif score >= 72:
        level = "very high"
    elif score >= 52:
        level = "high"
    elif score >= 34:
        level = "moderate"
    else:
        level = "low"

    return {
        "level": level,
        "score": round(min(100, score), 1),
        "drivers": {
            "magnitude": mag,
            "depth_km": depth,
            "tsunami_flag": bool(tsunami),
            "usgs_alert": alert or "none",
            "felt_reports": felt,
        },
    }

def get_disaster_risks():
    return [
        {
            "id": "pacific-tsunami",
            "name": "Pacific Tsunami Exposure Belt",
            "hazard": "tsunami",
            "risk_level": "extreme",
            "lat": 38.5,
            "lon": 143.5,
            "radius_km": 900,
            "region": "Northwest Pacific",
            "trigger": "Shallow offshore M7+ earthquakes and rapid seafloor displacement.",
            "safety": SAFETY_ACTIONS["tsunami"],
        },
        {
            "id": "sumatra-tsunami",
            "name": "Sumatra-Andaman Tsunami Corridor",
            "hazard": "tsunami",
            "risk_level": "extreme",
            "lat": 0.5,
            "lon": 96.5,
            "radius_km": 850,
            "region": "Indian Ocean",
            "trigger": "Megathrust rupture along the Sunda subduction interface.",
            "safety": SAFETY_ACTIONS["tsunami"],
        },
        {
            "id": "caucasus-landslide",
            "name": "Caucasus Slope Failure Zone",
            "hazard": "landslide",
            "risk_level": "moderate",
            "lat": 42.1,
            "lon": 44.6,
            "radius_km": 420,
            "region": "Georgia and Greater Caucasus",
            "trigger": "Earthquake shaking, heavy rain, snowmelt, and steep fractured terrain.",
            "safety": SAFETY_ACTIONS["landslide"],
        },
        {
            "id": "med-flood",
            "name": "Eastern Mediterranean Flash Flood Basins",
            "hazard": "flood",
            "risk_level": "high",
            "lat": 38.5,
            "lon": 28.0,
            "radius_km": 620,
            "region": "Greece, Turkey, Levant",
            "trigger": "Slow storms over steep urbanized catchments and coastal plains.",
            "safety": SAFETY_ACTIONS["flood"],
        },
        {
            "id": "california-wildfire",
            "name": "California Wildfire-Quake Cascading Risk",
            "hazard": "wildfire",
            "risk_level": "high",
            "lat": 36.5,
            "lon": -119.5,
            "radius_km": 700,
            "region": "California",
            "trigger": "Dry wind events, damaged utilities, post-quake access disruption.",
            "safety": SAFETY_ACTIONS["wildfire"],
        },
        {
            "id": "philippines-cyclone",
            "name": "Philippines Multi-Hazard Cyclone Corridor",
            "hazard": "cyclone",
            "risk_level": "very high",
            "lat": 13.5,
            "lon": 123.0,
            "radius_km": 650,
            "region": "Philippines",
            "trigger": "Tropical cyclones combining wind, surge, flood, landslide, and volcanic ash remobilization.",
            "safety": SAFETY_ACTIONS["cyclone"],
        },
        {
            "id": "andes-landslide",
            "name": "Andean Earthquake-Landslide Corridor",
            "hazard": "landslide",
            "risk_level": "high",
            "lat": -24.0,
            "lon": -70.0,
            "radius_km": 950,
            "region": "Chile and Peru",
            "trigger": "Strong shaking on steep slopes, mining roads, and dry valleys.",
            "safety": SAFETY_ACTIONS["landslide"],
        },
        {
            "id": "italy-volcanic",
            "name": "Southern Italy Volcanic and Ashfall Risk",
            "hazard": "volcano",
            "risk_level": "high",
            "lat": 40.8,
            "lon": 14.4,
            "radius_km": 260,
            "region": "Campania, Sicily, Tyrrhenian Sea",
            "trigger": "Volcanic unrest, ashfall, pyroclastic density currents, lahars, and local quakes.",
            "safety": SAFETY_ACTIONS["volcano"],
        },
    ]

def summarize_safety():
    quakes = get_earthquakes(4.5).get("features", [])
    risks = []
    for feature in quakes:
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [0, 0, 10])
        assessment = classify_earthquake(props, coords)
        risks.append({
            "kind": "earthquake",
            "name": props.get("place") or "Unknown earthquake",
            "risk_level": assessment["level"],
            "score": assessment["score"],
            "lat": coords[1],
            "lon": coords[0],
            "time": props.get("time"),
            "safety": SAFETY_ACTIONS["earthquake"],
            "drivers": assessment["drivers"],
        })

    for item in get_disaster_risks():
        risks.append({
            "kind": item["hazard"],
            "name": item["name"],
            "risk_level": item["risk_level"],
            "score": risk_score(item["risk_level"]) * 18,
            "lat": item["lat"],
            "lon": item["lon"],
            "time": None,
            "safety": item["safety"],
            "drivers": {"trigger": item["trigger"], "region": item["region"]},
        })

    risks.sort(key=lambda r: (risk_score(r["risk_level"]), r["score"]), reverse=True)
    return risks[:8]

def estimate_arrivals(eq_lat, eq_lon, depth_km, station_lat, station_lon):
    distance_km = haversine_km(eq_lat, eq_lon, station_lat, station_lon)
    hypo = math.sqrt(distance_km**2 + max(depth_km, 0)**2)

    # Simple educational approximation. Not a replacement for TauP/Iasp91.
    p_seconds = hypo / 6.2
    s_seconds = hypo / 3.6
    surface_seconds = distance_km / 3.2
    pkp_seconds = None
    deg = distance_km / 111.19
    if deg >= 100:
        pkp_seconds = 1100 + (deg - 100) * 7.5

    return {
        "distance_km": round(distance_km, 1),
        "hypocentral_km": round(hypo, 1),
        "distance_deg": round(deg, 2),
        "p_wave_seconds": round(p_seconds, 1),
        "s_wave_seconds": round(s_seconds, 1),
        "surface_wave_seconds": round(surface_seconds, 1),
        "pkp_wave_seconds": round(pkp_seconds, 1) if pkp_seconds else None,
    }

def get_seismic_stations():
    return [
        {"code":"IU.ANMO","name":"Albuquerque, NM","lat":34.9462,"lon":-106.4567,"network":"USGS-GSN","type":"broadband","country":"USA"},
        {"code":"IU.KONO","name":"Kongsberg","lat":59.6450,"lon":10.1817,"network":"USGS-GSN","type":"broadband","country":"Norway"},
        {"code":"IU.CHTO","name":"Chiang Mai","lat":18.7883,"lon":98.9853,"network":"USGS-GSN","type":"broadband","country":"Thailand"},
        {"code":"IU.CTAO","name":"Charters Towers","lat":-20.0881,"lon":146.2556,"network":"USGS-GSN","type":"broadband","country":"Australia"},
        {"code":"IU.TATO","name":"Taipei","lat":24.9744,"lon":120.9860,"network":"USGS-GSN","type":"broadband","country":"Taiwan"},
        {"code":"IU.INCN","name":"Incheon","lat":37.2756,"lon":126.6242,"network":"USGS-GSN","type":"broadband","country":"South Korea"},
        {"code":"IU.NWAO","name":"Nannup, WA","lat":-33.9367,"lon":115.1942,"network":"USGS-GSN","type":"broadband","country":"Australia"},
        {"code":"IU.SSPA","name":"South Pole","lat":-89.9,"lon":0.0,"network":"USGS-GSN","type":"broadband","country":"Antarctica"},
        {"code":"IU.RAYN","name":"Ar Rayn","lat":24.7088,"lon":44.6333,"network":"USGS-GSN","type":"broadband","country":"Saudi Arabia"},
        {"code":"IU.PMG","name":"Port Moresby","lat":-9.4045,"lon":147.1597,"network":"USGS-GSN","type":"broadband","country":"PNG"},
        {"code":"JP.JSA","name":"Aomori","lat":40.8236,"lon":140.7542,"network":"NIED","type":"broadband","country":"Japan"},
        {"code":"JP.SKN","name":"Tokyo/Shibuya","lat":35.6595,"lon":139.7004,"network":"NIED","type":"broadband","country":"Japan"},
        {"code":"TW.TWTW","name":"Taipei City","lat":25.0330,"lon":121.5654,"network":"CWBSN","type":"broadband","country":"Taiwan"},
        {"code":"KR.DAEGU","name":"Daegu","lat":35.8714,"lon":128.6014,"network":"KMA","type":"broadband","country":"South Korea"},
        {"code":"PH.SJM","name":"San José","lat":15.4894,"lon":120.5658,"network":"PHIVOLCS","type":"broadband","country":"Philippines"},
        {"code":"ID.PSSI","name":"Padang","lat":-1.0000,"lon":100.3333,"network":"BMKG-like","type":"broadband","country":"Indonesia"},
        {"code":"CN.BJT","name":"Beijing","lat":39.9519,"lon":116.2405,"network":"CENC-like","type":"broadband","country":"China"},
        {"code":"NZ.GISB","name":"Gisborne","lat":-38.6624,"lon":178.0497,"network":"GeoNet","type":"broadband","country":"New Zealand"},
        {"code":"US.NEIC","name":"Golden, CO","lat":39.7412,"lon":-105.2705,"network":"USGS","type":"broadband","country":"USA"},
        {"code":"US.MENLO","name":"Menlo Park","lat":37.4819,"lon":-122.2585,"network":"USGS","type":"broadband","country":"USA"},
        {"code":"MX.CDIG","name":"Mexico City","lat":19.4326,"lon":-99.1332,"network":"SSN","type":"broadband","country":"Mexico"},
        {"code":"CL.LVC","name":"Las Campanas","lat":-29.5,"lon":-70.5,"network":"Chile","type":"broadband","country":"Chile"},
        {"code":"BR.BDFB","name":"Brasília","lat":-15.8267,"lon":-47.8645,"network":"Brazil","type":"broadband","country":"Brazil"},
        {"code":"IT.ROM","name":"Rome","lat":41.9028,"lon":12.4964,"network":"INGV","type":"broadband","country":"Italy"},
        {"code":"IT.STIO","name":"Stromboli","lat":38.7920,"lon":15.2083,"network":"INGV","type":"broadband","country":"Italy"},
        {"code":"GR.ATH","name":"Athens","lat":37.9838,"lon":23.7275,"network":"Hellenic","type":"broadband","country":"Greece"},
        {"code":"TR.IZMIT","name":"Izmit","lat":40.7667,"lon":29.8667,"network":"AFAD","type":"broadband","country":"Turkey"},
        {"code":"GE.TBS","name":"Tbilisi","lat":41.7151,"lon":44.8271,"network":"Caucasus","type":"broadband","country":"Georgia"},
        {"code":"IS.AKUR","name":"Akureyri","lat":65.6835,"lon":-18.0882,"network":"IMO","type":"broadband","country":"Iceland"},
        {"code":"KP.HNL","name":"Honolulu","lat":21.3099,"lon":-157.8581,"network":"Pacific","type":"broadband","country":"USA"},
        {"code":"KP.GUMO","name":"Guam","lat":13.5889,"lon":144.8083,"network":"Pacific","type":"broadband","country":"Guam"},
    ]

def enrich_stations():
    stations = get_seismic_stations()
    eq_data = get_earthquakes(4.5).get("features", [])
    latest = None
    if eq_data:
        latest = sorted(eq_data, key=lambda f: f.get("properties", {}).get("time", 0) or 0, reverse=True)[0]

    for s in stations:
        seed = abs(hash(s["code"] + datetime.utcnow().strftime("%Y%m%d%H"))) % 1000
        rng = random.Random(seed)
        base_noise = rng.uniform(4, 28)

        if latest:
            coords = latest.get("geometry", {}).get("coordinates", [0, 0, 10])
            props = latest.get("properties", {})
            eq_lon, eq_lat = coords[0], coords[1]
            depth = coords[2] if len(coords) > 2 and coords[2] is not None else 10
            arrivals = estimate_arrivals(eq_lat, eq_lon, depth, s["lat"], s["lon"])
            mag = float(props.get("mag") or 0)
            dist = max(arrivals["distance_km"], 1)
            wave_boost = min(95, (mag * 1200) / (dist + 250))
            noise = min(100, base_noise + wave_boost + rng.uniform(0, 9))
            s["linked_event"] = {
                "magnitude": mag,
                "place": props.get("place"),
                "time": props.get("time"),
                "lat": eq_lat,
                "lon": eq_lon,
                "depth_km": depth,
            }
            s["arrival"] = arrivals
        else:
            noise = base_noise
            s["linked_event"] = None
            s["arrival"] = None

        s["noise_level"] = round(noise, 1)
        s["signal_quality"] = "excellent" if noise < 20 else "good" if noise < 40 else "noisy" if noise < 65 else "very noisy"
        s["coverage_radius_km"] = 950 if s["type"] == "broadband" else 350
        s["health"] = "nominal" if noise < 45 else "watch" if noise < 70 else "degraded"
        s["latency_seconds"] = round(rng.uniform(0.4, 4.8) + (noise / 55), 1)
        s["risk_role"] = "regional early characterization" if s["coverage_radius_km"] >= 900 else "local intensity support"
        s["last_packet_utc"] = now_iso()

    return stations

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok",
        "generated_utc": now_iso(),
        "service": "Seismic Disaster Tracker",
        "mode": "local"
    })


@app.route("/api/earthquakes")
def api_earthquakes():
    mag = float(request.args.get("mag_filter", 0))
    return jsonify(get_earthquakes(mag))

@app.route("/api/volcanoes")
def api_volcanoes():
    data = get_volcanoes()
    return jsonify({"volcanoes": data, "count": len(data)})

@app.route("/api/faults")
def api_faults():
    data = get_faults()
    return jsonify({"faults": data, "count": len(data)})

@app.route("/api/disaster-risks")
def api_disaster_risks():
    data = get_disaster_risks()
    return jsonify({"risks": data, "count": len(data), "safety_actions": SAFETY_ACTIONS})

@app.route("/api/safety-summary")
def api_safety_summary():
    data = summarize_safety()
    return jsonify({
        "summary": data,
        "count": len(data),
        "generated_utc": now_iso(),
        "note": "Educational situational-awareness triage. Follow official alerts and local emergency management.",
    })

@app.route("/api/stations")
def api_stations():
    data = enrich_stations()
    return jsonify({"stations": data, "count": len(data), "note": "Station wave/noise values are simulated educational overlays based on nearest/latest M4.5+ event geometry."})

@app.route("/api/station-arrivals")
def api_station_arrivals():
    eq_lat = float(request.args.get("eq_lat"))
    eq_lon = float(request.args.get("eq_lon"))
    depth = float(request.args.get("depth", 10))
    output = []
    for station in get_seismic_stations():
        s = dict(station)
        s["arrival"] = estimate_arrivals(eq_lat, eq_lon, depth, station["lat"], station["lon"])
        output.append(s)
    return jsonify({"stations": output, "count": len(output)})

def open_browser_later():
    time.sleep(1.2)
    webbrowser.open("http://127.0.0.1:5000")

if __name__ == "__main__":
    if os.environ.get("SEISMIC_NO_BROWSER") != "1":
        threading.Thread(target=open_browser_later, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
