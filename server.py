from flask import Flask, Response, send_from_directory, request, jsonify
import requests
import json
import os
from tsunami_warning import TsunamiWarningSystem, format_tsunami_report
from intensity_calculator import IntensityCalculator, FaultType
from location_search import LocationSearcher
from live_earthquake_detector import LiveEarthquakeDetector

app = Flask(__name__, static_folder=".", static_url_path="/static")

@app.route("/")
def index():
    return send_from_directory(".", "Index-Globe.html")

@app.route("/<path:filename>")
def serve_static(filename):
    """Serve static files (JS, CSS, etc)"""
    if os.path.exists(os.path.join(".", filename)):
        return send_from_directory(".", filename)
    return jsonify({"error": "Not found"}), 404

@app.route("/proxy/stations/iris")
def iris_stations():
    url = (
        "https://service.iris.edu/fdsnws/station/1/query"
        "?level=station"
        "&format=text"
        "&nodata=404"
    )

    headers = {
        "User-Agent": "OpenSeismo-Lite/1.0"
    }

    try:
        r = requests.get(url, headers=headers, timeout=25)
        return Response(
            r.text,
            status=r.status_code,
            content_type="text/plain"
        )
    except Exception as e:
        return Response(str(e), status=502, content_type="text/plain")


@app.route("/proxy/stations/geofon")
def geofon_stations():
    url = (
        "https://geofon.gfz-potsdam.de/fdsnws/station/1/query"
        "?level=station"
        "&format=text"
        "&nodata=404"
    )

    headers = {
        "User-Agent": "OpenSeismo-Lite/1.0"
    }

    try:
        r = requests.get(url, headers=headers, timeout=25)
        return Response(
            r.text,
            status=r.status_code,
            content_type="text/plain"
        )
    except Exception as e:
        return Response(str(e), status=502, content_type="text/plain")


@app.route("/api/tsunami/evaluate", methods=["POST"])
def evaluate_tsunami():
    """
    Evaluate tsunami risk for an earthquake
    Expected JSON: {
        "magnitude": float,
        "depth_km": float,
        "latitude": float,
        "longitude": float,
        "time": string (ISO format)
    }
    """
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['magnitude', 'depth_km', 'latitude', 'longitude']):
            return jsonify({"error": "Missing required fields"}), 400
        
        result = TsunamiWarningSystem.evaluate_earthquake(
            magnitude=data['magnitude'],
            depth_km=data['depth_km'],
            latitude=data['latitude'],
            longitude=data['longitude']
        )
        
        # Add metadata
        result['time'] = data.get('time', '')
        result['analysis_time'] = __import__('datetime').datetime.utcnow().isoformat()
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tsunami/info")
def tsunami_info():
    """Get tsunami warning system information and thresholds"""
    info = {
        "system": "JMA-inspired Tsunami Warning System",
        "warning_levels": {
            "MAJOR_WARNING": {
                "description": "Major tsunami warning - expect destructive waves",
                "wave_height_threshold_m": 3.0,
                "color": "#DC2626"
            },
            "WARNING": {
                "description": "Tsunami warning - dangerous waves expected",
                "wave_height_threshold_m": 1.0,
                "color": "#EA580C"
            },
            "ADVISORY": {
                "description": "Tsunami advisory - minor waves may occur",
                "wave_height_threshold_m": 0.5,
                "color": "#F59E0B"
            },
            "NO_WARNING": {
                "description": "No tsunami threat detected",
                "wave_height_threshold_m": 0.0,
                "color": "#10B981"
            }
        },
        "monitored_regions": [
            "Japan", "Indonesia", "Philippines", "New Zealand",
            "US West Coast", "Chile", "Thailand"
        ],
        "minimum_magnitude_for_warning": 6.5,
        "note": "This is an educational tsunami warning system and NOT an official EEW/TWS system"
    }
    return jsonify(info), 200


@app.route("/api/intensity/mmi-shindo", methods=["POST"])
def calculate_intensity():
    """
    Calculate MMI and Shindo intensities for an earthquake
    Expected JSON: {
        "magnitude": float,
        "depth_km": float,
        "latitude": float,
        "longitude": float,
        "distance_km": float (optional, default 0.1)
    }
    """
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['magnitude', 'depth_km', 'latitude', 'longitude']):
            return jsonify({"error": "Missing required fields: magnitude, depth_km, latitude, longitude"}), 400
        
        magnitude = data['magnitude']
        depth_km = data['depth_km']
        latitude = data['latitude']
        longitude = data['longitude']
        distance_km = data.get('distance_km', 0.1)
        
        # Classify fault type
        fault_type, fault_zone_info = IntensityCalculator.classify_fault_type(latitude, longitude, depth_km)
        
        # Calculate intensities
        mmi = IntensityCalculator.calculate_mmi(magnitude, depth_km, distance_km, fault_type)
        shindo = IntensityCalculator.calculate_shindo(magnitude, depth_km, distance_km, fault_type)
        
        # Get scale information
        mmi_scale = IntensityCalculator.get_mmi_scale(mmi)
        shindo_scale = IntensityCalculator.get_shindo_scale(shindo)
        
        result = {
            "magnitude": magnitude,
            "depth_km": depth_km,
            "distance_km": distance_km,
            "latitude": latitude,
            "longitude": longitude,
            "fault_type": fault_type.value,
            "fault_zone": {
                "type": fault_zone_info.fault_type.value,
                "color": fault_zone_info.color,
                "description": fault_zone_info.description,
                "typical_depth_range": f"{fault_zone_info.typical_depth_min}-{fault_zone_info.typical_depth_max} km"
            },
            "mmi": {
                "value": round(mmi, 2),
                "scale": mmi_scale.name,
                "description": mmi_scale.description,
                "color": mmi_scale.color,
                "integer": int(round(mmi))
            },
            "shindo": {
                "value": round(shindo, 2),
                "scale": shindo_scale.name,
                "description": shindo_scale.description,
                "color": shindo_scale.color
            }
        }
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/intensity/report", methods=["POST"])
def intensity_report():
    """
    Generate comprehensive intensity report for an earthquake
    Expected JSON: {
        "magnitude": float,
        "depth_km": float,
        "latitude": float,
        "longitude": float
    }
    """
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['magnitude', 'depth_km', 'latitude', 'longitude']):
            return jsonify({"error": "Missing required fields"}), 400
        
        report = IntensityCalculator.get_intensity_report(
            magnitude=data['magnitude'],
            depth_km=data['depth_km'],
            latitude=data['latitude'],
            longitude=data['longitude']
        )
        
        return jsonify(report), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/intensity/grid", methods=["POST"])
def intensity_grid():
    """
    Calculate intensity grid around epicenter
    Expected JSON: {
        "magnitude": float,
        "depth_km": float,
        "latitude": float,
        "longitude": float,
        "grid_size_km": int (optional, default 50),
        "max_distance_km": int (optional, default 500)
    }
    """
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['magnitude', 'depth_km', 'latitude', 'longitude']):
            return jsonify({"error": "Missing required fields"}), 400
        
        grid_points = IntensityCalculator.calculate_intensity_grid(
            magnitude=data['magnitude'],
            depth_km=data['depth_km'],
            latitude=data['latitude'],
            longitude=data['longitude'],
            grid_size_km=data.get('grid_size_km', 50),
            max_distance_km=data.get('max_distance_km', 500)
        )
        
        return jsonify({
            "magnitude": data['magnitude'],
            "depth_km": data['depth_km'],
            "latitude": data['latitude'],
            "longitude": data['longitude'],
            "grid_points": grid_points,
            "point_count": len(grid_points)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/intensity/info")
def intensity_info():
    """Get intensity scale information and descriptions"""
    return jsonify({
        "mmi_scale": {
            "name": "Modified Mercalli Intensity Scale",
            "description": "Measures the effects of earthquakes on the Earth's surface, human beings, buildings, and other structures",
            "range": "I (not felt) to XII (total destruction)",
            "levels": {
                "I": {"value": 1, "description": "Not felt", "color": "#ffffff"},
                "II": {"value": 2, "description": "Weak - Felt indoors", "color": "#ccccff"},
                "III": {"value": 3, "description": "Weak - Felt indoors, vibrations like passing truck", "color": "#99ccff"},
                "IV": {"value": 4, "description": "Light - Indoor objects rattle, felt outdoors", "color": "#66ccff"},
                "V": {"value": 5, "description": "Moderate - Felt by most, some dishes break", "color": "#00ccff"},
                "VI": {"value": 6, "description": "Strong - Felt by all, minor damage", "color": "#ffff00"},
                "VII": {"value": 7, "description": "Very Strong - Considerable damage, everyone runs outside", "color": "#ffcc00"},
                "VIII": {"value": 8, "description": "Severe - Structural damage, partial collapse", "color": "#ff9900"},
                "IX": {"value": 9, "description": "Violent - Considerable damage, ground cracking", "color": "#ff6600"},
                "X": {"value": 10, "description": "Extreme - Most buildings destroyed", "color": "#ff3300"},
                "XI": {"value": 11, "description": "Extreme - Few buildings standing", "color": "#ff0000"},
                "XII": {"value": 12, "description": "Extreme - Total destruction", "color": "#cc0000"}
            }
        },
        "shindo_scale": {
            "name": "Japan Meteorological Agency Shindo Scale",
            "description": "Japanese seismic intensity scale used by the Japan Meteorological Agency",
            "range": "0 (not felt) to 7 (extreme destruction)",
            "levels": {
                "0": {"value": 0, "description": "Not felt", "color": "#ffffff"},
                "1": {"value": 1, "description": "Weak - Felt indoors", "color": "#ccccff"},
                "2": {"value": 2, "description": "Light - Objects rattle", "color": "#66ccff"},
                "3": {"value": 3, "description": "Moderate - Most people frightened", "color": "#00ccff"},
                "4": {"value": 4, "description": "Strong - Most buildings slightly damaged", "color": "#ffff00"},
                "5-": {"value": 5.0, "description": "Strong - Many buildings damaged", "color": "#ffcc00"},
                "5+": {"value": 5.5, "description": "Strong+ - Considerable damage", "color": "#ff9900"},
                "6-": {"value": 6.0, "description": "Very Strong - Many buildings collapse", "color": "#ff6600"},
                "6+": {"value": 6.5, "description": "Very Strong+ - Most buildings collapse", "color": "#ff3300"},
                "7": {"value": 7.0, "description": "Extreme - Total/near total destruction", "color": "#cc0000"}
            }
        },
        "fault_zones": {
            "subduction": {
                "color": "#0066cc",
                "description": "Subduction Zone - High tsunami and magnitude risk",
                "typical_depth": "0-700 km",
                "examples": ["Japan Trench", "Peru-Chile Trench", "Mariana Trench"]
            },
            "transform": {
                "color": "#ff6600",
                "description": "Transform Fault - Strong lateral motion",
                "typical_depth": "0-50 km",
                "examples": ["San Andreas Fault", "Alpine Fault (NZ)"]
            },
            "reverse_thrust": {
                "color": "#cc0000",
                "description": "Reverse-Thrust Fault - Vertical uplift, potential tsunami",
                "typical_depth": "0-300 km",
                "examples": ["Himalayas", "Zagros Mountains"]
            },
            "normal": {
                "color": "#00cc66",
                "description": "Normal Fault - Extensional stress",
                "typical_depth": "0-30 km",
                "examples": ["East African Rift"]
            },
            "divergent": {
                "color": "#66ccff",
                "description": "Divergent Boundary - Seafloor spreading",
                "typical_depth": "0-20 km",
                "examples": ["Mid-Atlantic Ridge", "East Pacific Rise"]
            },
            "convergent": {
                "color": "#9900cc",
                "description": "Convergent Boundary - Compression zone",
                "typical_depth": "0-250 km",
                "examples": ["Alpine Belt"]
            },
            "strike_slip": {
                "color": "#ffcc00",
                "description": "Strike-Slip Fault - Horizontal motion",
                "typical_depth": "0-30 km",
                "examples": ["San Andreas", "Dead Sea Transform"]
            }
        }
    }), 200


@app.route("/api/location/search", methods=["GET", "POST"])
def location_search():
    """
    Search for locations by name or coordinates
    Expected parameters:
    - GET: query=<location name or "lat,lon">
    - POST JSON: {"query": "<location name or coordinates>"}
    """
    try:
        if request.method == "POST":
            data = request.get_json() or {}
            query = data.get('query', '').strip()
        else:
            query = request.args.get('query', '').strip()
        
        if not query:
            return jsonify({"error": "Query parameter required"}), 400
        
        result = LocationSearcher.search(query)
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/location/info", methods=["POST"])
def location_info():
    """
    Get comprehensive location information
    Expected JSON: {
        "latitude": float,
        "longitude": float
    }
    """
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['latitude', 'longitude']):
            return jsonify({"error": "latitude and longitude required"}), 400
        
        info = LocationSearcher.get_location_info(
            latitude=data['latitude'],
            longitude=data['longitude']
        )
        
        return jsonify(info), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/location/nearby", methods=["POST"])
def location_nearby():
    """
    Find nearby cities and tectonic regions
    Expected JSON: {
        "latitude": float,
        "longitude": float
    }
    """
    try:
        data = request.get_json()
        
        if not all(k in data for k in ['latitude', 'longitude']):
            return jsonify({"error": "latitude and longitude required"}), 400
        
        nearby = LocationSearcher.search_by_coordinates(
            latitude=data['latitude'],
            longitude=data['longitude']
        )
        
        return jsonify(nearby), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/location/suggestions")
def location_suggestions():
    """
    Get list of major cities for autocomplete suggestions
    """
    try:
        suggestions = []
        
        # Add major cities
        for city in LocationSearcher.MAJOR_CITIES:
            suggestions.append({
                'name': city['name'],
                'type': 'city',
                'country': city['country']
            })
        
        # Add tectonic regions
        for region in LocationSearcher.TECTONIC_REGIONS:
            suggestions.append({
                'name': region['name'],
                'type': 'tectonic_region'
            })
        
        return jsonify({
            'suggestions': sorted(suggestions, key=lambda x: x['name']),
            'total_count': len(suggestions)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/earthquakes/live", methods=["GET"])
def get_live_earthquakes():
    """
    Get current live earthquakes with ShakeMax intensities and hexagon grids
    Query parameters:
        - magnitude_filter: Minimum magnitude (default: 4.5)
        - enrich: Whether to include ShakeMax and hexagon data (default: true)
    """
    try:
        magnitude_filter = request.args.get('magnitude_filter', 4.5, type=float)
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        earthquakes = LiveEarthquakeDetector.get_live_earthquakes(
            magnitude_filter=magnitude_filter,
            enrich=enrich
        )
        
        return jsonify({
            "status": "success",
            "count": len(earthquakes),
            "timestamp": __import__('datetime').datetime.utcnow().isoformat() + 'Z',
            "earthquakes": earthquakes
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e), "count": 0, "earthquakes": []}), 500


@app.route("/api/earthquakes/live/<eq_id>", methods=["GET"])
def get_earthquake_detail(eq_id):
    """
    Get detailed information for a specific earthquake
    """
    try:
        earthquakes = LiveEarthquakeDetector.get_live_earthquakes(magnitude_filter=0, enrich=True)
        
        for eq in earthquakes:
            if eq['id'] == eq_id:
                return jsonify({
                    "status": "success",
                    "earthquake": eq
                }), 200
        
        return jsonify({"error": "Earthquake not found"}), 404
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/earthquakes/shakemax-grid/<eq_id>", methods=["GET"])
def get_shakemax_grid(eq_id):
    """
    Get ShakeMax hexagon grid for a specific earthquake
    Query parameters:
        - grid_radius: Radius in km (default: 300)
        - hex_size: Hexagon size in km (default: 15)
    """
    try:
        earthquakes = LiveEarthquakeDetector.get_live_earthquakes(magnitude_filter=0, enrich=False)
        
        eq = None
        for earthquake in earthquakes:
            if earthquake['id'] == eq_id:
                eq = earthquake
                break
        
        if not eq:
            return jsonify({"error": "Earthquake not found"}), 404
        
        grid_radius = request.args.get('grid_radius', 300, type=int)
        hex_size = request.args.get('hex_size', 15, type=int)
        
        hexagons = LiveEarthquakeDetector.generate_hexagon_grid(
            latitude=eq['latitude'],
            longitude=eq['longitude'],
            magnitude=eq['magnitude'],
            depth_km=eq['depth_km'],
            grid_radius_km=grid_radius,
            hex_size_km=hex_size
        )
        
        return jsonify({
            "status": "success",
            "earthquake_id": eq_id,
            "magnitude": eq['magnitude'],
            "latitude": eq['latitude'],
            "longitude": eq['longitude'],
            "depth_km": eq['depth_km'],
            "hexagon_count": len(hexagons),
            "grid_radius_km": grid_radius,
            "hexagon_size_km": hex_size,
            "hexagons": hexagons
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/earthquakes/shakemax-levels", methods=["GET"])
def get_shakemax_levels():
    """
    Get ShakeMax intensity level definitions for legend display
    """
    try:
        return jsonify({
            "status": "success",
            "levels": LiveEarthquakeDetector.SHAKEMAX_LEVELS
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("OpenSeismo Lite running at: http://localhost:5000")
    # CRITICAL: Never use debug=True or use_reloader=True in production builds
    # These cause infinite tab spawning in PyInstaller executables
    app.run(
        host="127.0.0.1", 
        port=5000, 
        debug=False,           # MUST be False
        use_reloader=False,    # MUST be False
        use_debugger=False     # Extra safety
    )
