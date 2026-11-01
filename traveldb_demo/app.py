import os
import json
import math
import urllib.error
import urllib.request
from urllib.parse import urlencode
from decimal import Decimal, InvalidOperation

import mysql.connector
from flask import Flask, flash, redirect, render_template, request, url_for
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-key-before-demo")

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "").strip()

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "TravelDB"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "connection_timeout": 5,
}

SERVICE_TYPES = [
    ("hospital", "Hospitals"),
    ("petrol_pump", "Petrol pumps"),
    ("ev_station", "EV charging stations"),
    ("hotel", "Hotels"),
    ("restaurant", "Restaurants"),
]
SERVICE_TYPE_LABELS = dict(SERVICE_TYPES)
TRAVEL_MODES = ["Car", "Motorcycle", "EV", "Public Transport"]


def get_connection():
    """Open a short-lived connection to the TravelDB MySQL database."""
    return mysql.connector.connect(**DB_CONFIG)


def fetch_cities():
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT C.CityID, C.CityName, S.StateName
               FROM CITY C
               JOIN STATE S ON S.StateID = C.StateID
               WHERE C.CityName IS NOT NULL AND TRIM(C.CityName) <> ''
               ORDER BY C.CityName, C.CityID"""
        )
        return cur.fetchall()
    finally:
        conn.close()


def fetch_plan(plan_id):
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT P.PlanID, P.PlanName, P.SourceCityID, P.DestinationCityID,
                      P.TravelMode, P.Notes, P.CreatedAt,
                      SC.CityName AS SourceCity, DC.CityName AS DestinationCity
               FROM SAVED_TRIP_PLAN P
               JOIN CITY SC ON SC.CityID = P.SourceCityID
               JOIN CITY DC ON DC.CityID = P.DestinationCityID
               WHERE P.PlanID = %s""",
            (plan_id,),
        )
        return cur.fetchone()
    finally:
        conn.close()


@app.template_filter("number")
def format_number(value, decimals=2):
    if value is None:
        return "—"
    try:
        return f"{float(value):,.{int(decimals)}f}"
    except (TypeError, ValueError):
        return value


@app.route("/")
def index():
    stats = {}
    error = None
    try:
        conn = get_connection()
        try:
            cur = conn.cursor(dictionary=True)
            checks = {
                "roads": "SELECT COUNT(*) AS n FROM ROAD_SEGMENT",
                "cities": "SELECT COUNT(*) AS n FROM CITY WHERE CityName IS NOT NULL AND TRIM(CityName) <> ''",
                "services": "SELECT COUNT(*) AS n FROM SERVICE_LOCATION",
                "routes": "SELECT COUNT(*) AS n FROM ROUTE",
                "traffic": "SELECT COUNT(*) AS n FROM TRAFFIC_RECORD",
            }
            for key, sql in checks.items():
                cur.execute(sql)
                stats[key] = cur.fetchone()["n"]
        finally:
            conn.close()
    except mysql.connector.Error as exc:
        error = (
            "Could not connect to TravelDB. Check that MySQL is running, the .env "
            "credentials are correct, and you executed setup.sql. Details: " + str(exc)
        )
    return render_template("index.html", stats=stats, error=error)


def get_osrm_routes(source_lat, source_lon, destination_lat, destination_lon, alternative_count=2):
    """Request up to three candidate driving routes, full line geometry, and turn steps."""
    coordinates = f"{float(source_lon)},{float(source_lat)};{float(destination_lon)},{float(destination_lat)}"
    params = urlencode({
        "overview": "full",
        "geometries": "geojson",
        "alternatives": str(alternative_count),
        "steps": "true",
    })
    osrm_url = f"https://router.project-osrm.org/route/v1/driving/{coordinates}?{params}"
    req = urllib.request.Request(
        osrm_url,
        headers={"User-Agent": "TravelDB-Student-Project/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    options = payload.get("routes") or []
    if payload.get("code") != "Ok" or not options:
        raise ValueError(
            "The routing service could not calculate a driving path for these places. "
            "Try another source/destination pair or check your internet connection."
        )
    return options


def make_turn_instruction(step):
    """Convert an OSRM step into a readable driving instruction."""
    maneuver = step.get("maneuver") or {}
    kind = (maneuver.get("type") or "continue").lower()
    modifier = (maneuver.get("modifier") or "").lower()
    road_name = (step.get("name") or step.get("ref") or step.get("destinations") or "").strip()
    direction_words = {
        "left": "left", "right": "right", "slight left": "slightly left",
        "slight right": "slightly right", "sharp left": "sharply left",
        "sharp right": "sharply right", "uturn": "make a U-turn",
        "straight": "straight",
    }

    if kind == "depart":
        text = "Start"
        if road_name:
            text += f" on {road_name}"
    elif kind == "arrive":
        text = "Arrive at your destination"
    elif kind in {"roundabout", "rotary", "roundabout turn"}:
        exit_number = maneuver.get("exit")
        text = f"Enter the roundabout and take exit {exit_number}" if exit_number else "Enter the roundabout and follow signs"
    elif kind == "exit roundabout":
        text = "Exit the roundabout"
    elif kind == "fork":
        text = f"Keep {direction_words.get(modifier, modifier or 'straight')}"
    elif kind == "merge":
        text = f"Merge {direction_words.get(modifier, modifier)}" if modifier else "Merge"
    elif kind == "on ramp":
        text = "Take the entrance ramp"
        if modifier:
            text += f" to the {direction_words.get(modifier, modifier)}"
    elif kind == "off ramp":
        text = "Take the exit ramp"
        if modifier:
            text += f" to the {direction_words.get(modifier, modifier)}"
    elif kind == "end of road":
        text = "At the end of the road"
        if modifier in direction_words:
            text += f", turn {direction_words[modifier]}"
    elif kind == "turn":
        if modifier == "uturn":
            text = "Make a U-turn"
        elif modifier == "straight":
            text = "Continue straight"
        elif modifier:
            text = f"Turn {direction_words.get(modifier, modifier)}"
        else:
            text = "Turn as indicated"
    elif kind in {"continue", "new name", "notification"}:
        if modifier in direction_words and modifier != "straight":
            text = f"Continue {direction_words[modifier]}"
        else:
            text = "Continue straight"
    else:
        text = "Continue as indicated"

    if road_name and kind not in {"depart", "arrive"} and road_name.lower() not in text.lower():
        text += f" onto {road_name}"

    distance_m = float(step.get("distance") or 0.0)
    duration_s = float(step.get("duration") or 0.0)
    location = maneuver.get("location") or []  # OSRM returns [longitude, latitude].
    lon = float(location[0]) if len(location) >= 2 and location[0] is not None else None
    lat = float(location[1]) if len(location) >= 2 and location[1] is not None else None
    return {
        "Instruction": text,
        "RoadName": road_name,
        "DistanceKm": distance_m / 1000.0,
        "DurationMinutes": duration_s / 60.0,
        "Lat": lat,
        "Lon": lon,
        "ManeuverType": kind,
        "Modifier": modifier,
    }


def extract_turn_by_turn(osrm_route):
    """Flatten OSRM legs into ordered instructions with coordinates for map markers."""
    directions = []
    for leg in (osrm_route.get("legs") or []):
        for step in (leg.get("steps") or []):
            item = make_turn_instruction(step)
            item["StepNumber"] = len(directions) + 1
            directions.append(item)
    return directions


# Traffic-aware decision support. Live flow data is fetched at request time and
# is not persisted locally; check your provider's licence before caching API content.
def sample_route_points(route_geometry, max_points=3):
    """Pick evenly spaced points along an OSRM GeoJSON line for live-flow sampling."""
    if not route_geometry or route_geometry.get("type") != "LineString":
        return []
    coords = route_geometry.get("coordinates") or []
    if len(coords) < 2:
        return []
    max_points = max(1, min(int(max_points), len(coords)))
    if max_points == 1:
        fractions = [0.5]
    else:
        fractions = [(i + 1) / (max_points + 1) for i in range(max_points)]
    indexes = []
    for fraction in fractions:
        idx = int(round((len(coords) - 1) * fraction))
        if idx not in indexes:
            indexes.append(idx)
    return [{"lon": float(coords[i][0]), "lat": float(coords[i][1]), "sample": n + 1}
            for n, i in enumerate(indexes)]


def fetch_tomtom_flow(latitude, longitude):
    """Fetch live speed/travel-time info for the nearest road segment to a coordinate."""
    if not TOMTOM_API_KEY:
        return None
    params = urlencode({
        "key": TOMTOM_API_KEY,
        "point": f"{float(latitude):.6f},{float(longitude):.6f}",
        "unit": "KMPH",
    })
    url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json?" + params
    req = urllib.request.Request(url, headers={"User-Agent": "TravelDB-Student-Project/1.0"})
    with urllib.request.urlopen(req, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    flow = payload.get("flowSegmentData") or {}
    required = ("currentSpeed", "freeFlowSpeed", "currentTravelTime", "freeFlowTravelTime")
    if any(flow.get(k) is None for k in required):
        raise ValueError("Traffic provider returned an incomplete flow record.")
    current_speed = float(flow["currentSpeed"])
    free_speed = float(flow["freeFlowSpeed"])
    current_time = float(flow["currentTravelTime"])
    free_time = float(flow["freeFlowTravelTime"])
    if free_speed <= 0 or free_time <= 0:
        raise ValueError("Traffic provider returned invalid free-flow values.")
    speed_ratio = current_speed / free_speed
    return {
        "current_speed": current_speed,
        "free_flow_speed": free_speed,
        "current_time": current_time,
        "free_flow_time": free_time,
        "confidence": float(flow.get("confidence") or 0.0),
        "road_closure": bool(flow.get("roadClosure", False)),
        "congestion_pct": max(0.0, min(100.0, (1.0 - speed_ratio) * 100.0)),
        "delay_factor": max(1.0, current_time / free_time),
    }


def get_live_route_traffic(route_geometry, max_points=3):
    """Sample current traffic along a route; return a summary or a user-facing status."""
    if not TOMTOM_API_KEY:
        return None, "Live traffic is not configured. Add TOMTOM_API_KEY to your .env file to enable it."
    points = sample_route_points(route_geometry, max_points=max_points)
    if not points:
        return None, "A route line is unavailable, so traffic could not be sampled along this route."
    records = []
    errors = []
    for point in points:
        try:
            record = fetch_tomtom_flow(point["lat"], point["lon"])
            if record:
                record["sample"] = point["sample"]
                records.append(record)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
    if not records:
        return None, "The live traffic service did not return usable observations. Check the API key, quota and internet connection."
    mean = lambda key: sum(r[key] for r in records) / len(records)
    congestion = mean("congestion_pct")
    delay_factor = mean("delay_factor")
    closure_detected = any(r["road_closure"] for r in records)
    if closure_detected:
        level = "Possible closure at a sampled point"
    elif congestion < 10:
        level = "Light / near free-flow"
    elif congestion < 25:
        level = "Moderate"
    elif congestion < 45:
        level = "Heavy"
    else:
        level = "Severe"
    summary = {
        "provider": "TomTom Traffic Flow",
        "sample_count": len(records),
        "current_speed": mean("current_speed"),
        "free_flow_speed": mean("free_flow_speed"),
        "congestion_pct": congestion,
        "delay_pct": max(0.0, (delay_factor - 1.0) * 100.0),
        "delay_factor": delay_factor,
        "confidence_pct": mean("confidence") * 100.0,
        "road_closure": closure_detected,
        "level": level,
        "observed_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "partial_warning": "Some route samples failed; summary uses successful samples." if errors and records else None,
    }
    return summary, None


def fetch_services_in_route_corridor(candidates, selected_types, radius_km):
    """Fetch selected amenities inside the bounding corridor of candidate route geometries."""
    if not selected_types:
        return []
    all_coords = []
    for candidate in candidates:
        geometry = candidate.get("geometry") or {}
        if geometry.get("type") == "LineString":
            all_coords.extend(geometry.get("coordinates") or [])
    all_coords = [coord for coord in all_coords if isinstance(coord, (list, tuple)) and len(coord) >= 2]
    if not all_coords:
        return []

    lons = [float(c[0]) for c in all_coords]
    lats = [float(c[1]) for c in all_coords]
    mean_lat = sum(lats) / len(lats)
    lat_margin = float(radius_km) / 110.574
    cos_lat = max(0.15, abs(math.cos(math.radians(mean_lat))))
    lon_margin = float(radius_km) / (111.320 * cos_lat)
    type_placeholders = ",".join(["%s"] * len(selected_types))
    sql = f"""SELECT ServiceLocationID, OSM_ID, Name, LocationType, Address,
                      Latitude, Longitude, Operator, Brand, Postcode
               FROM SERVICE_LOCATION
               WHERE LocationType IN ({type_placeholders})
                 AND Latitude IS NOT NULL AND Longitude IS NOT NULL
                 AND Latitude BETWEEN %s AND %s
                 AND Longitude BETWEEN %s AND %s"""
    params = list(selected_types) + [min(lats) - lat_margin, max(lats) + lat_margin,
                                    min(lons) - lon_margin, max(lons) + lon_margin]
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        for row in rows:
            row["Latitude"] = float(row["Latitude"])
            row["Longitude"] = float(row["Longitude"])
        return rows
    finally:
        conn.close()


def _sample_route_coords(geometry, max_points=350):
    """Downsample a dense route polyline to a size suitable for amenity proximity checks."""
    if not geometry or geometry.get("type") != "LineString":
        return []
    coords = geometry.get("coordinates") or []
    coords = [(float(c[0]), float(c[1])) for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
    if len(coords) <= max_points:
        return coords
    step = (len(coords) - 1) / float(max_points - 1)
    sampled = [coords[int(round(i * step))] for i in range(max_points)]
    # Remove duplicate samples caused by rounding.
    out = []
    for coord in sampled:
        if not out or coord != out[-1]:
            out.append(coord)
    return out


def _project_route_for_distance(coords):
    """Project route samples to a local kilometre plane and return line segments."""
    if len(coords) < 2:
        return [], None
    lat0 = sum(c[1] for c in coords) / len(coords)
    lon0 = sum(c[0] for c in coords) / len(coords)
    x_scale = 111.320 * math.cos(math.radians(lat0))
    y_scale = 110.574
    projected = [((lon - lon0) * x_scale, (lat - lat0) * y_scale) for lon, lat in coords]
    segments = [(projected[i][0], projected[i][1], projected[i + 1][0], projected[i + 1][1])
                for i in range(len(projected) - 1)]
    return segments, (lat0, lon0, x_scale, y_scale)


def _point_to_segments_distance_km(service, segments, projection):
    """Approximate point-to-route distance in km using local equirectangular projection."""
    lat0, lon0, x_scale, y_scale = projection
    px = (float(service["Longitude"]) - lon0) * x_scale
    py = (float(service["Latitude"]) - lat0) * y_scale
    best_sq = float("inf")
    for x1, y1, x2, y2 in segments:
        dx = x2 - x1
        dy = y2 - y1
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            t = 0.0
        else:
            t = ((px - x1) * dx + (py - y1) * dy) / denom
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
        qx = x1 + t * dx
        qy = y1 + t * dy
        dsq = (px - qx) ** 2 + (py - qy) ** 2
        if dsq < best_sq:
            best_sq = dsq
            if best_sq <= 0.0001:
                break
    return math.sqrt(best_sq) if best_sq < float("inf") else None


def score_route_service_proximity(candidate, service_locations, selected_types, radius_km):
    """Score how close a route runs to the nearest service of each selected type.

    Each selected category contributes equally. A matching service on the route scores
    100; a service exactly at the corridor radius scores 0; no match in the corridor scores 0.
    """
    geometry = candidate.get("geometry") or {}
    coords = _sample_route_coords(geometry)
    segments, projection = _project_route_for_distance(coords)
    if not segments or projection is None:
        return [], None

    grouped = {service_type: [] for service_type in selected_types}
    for service in service_locations:
        service_type = service.get("LocationType")
        if service_type in grouped:
            grouped[service_type].append(service)

    details = []
    for service_type in selected_types:
        nearest = None
        nearest_distance = None
        for service in grouped.get(service_type, []):
            distance = _point_to_segments_distance_km(service, segments, projection)
            if distance is not None and (nearest_distance is None or distance < nearest_distance):
                nearest = service
                nearest_distance = distance
                if distance <= 0.01:
                    break
        found = nearest is not None and nearest_distance is not None and nearest_distance <= float(radius_km)
        score = 100.0 * max(0.0, 1.0 - nearest_distance / float(radius_km)) if found else 0.0
        details.append({
            "Type": service_type,
            "Label": SERVICE_TYPE_LABELS.get(service_type, service_type.replace("_", " ").title()),
            "ServiceLocationID": nearest.get("ServiceLocationID") if nearest else None,
            "Name": nearest.get("Name") if nearest else None,
            "LocationType": service_type,
            "Address": nearest.get("Address") if nearest else None,
            "Latitude": nearest.get("Latitude") if nearest else None,
            "Longitude": nearest.get("Longitude") if nearest else None,
            "Brand": nearest.get("Brand") if nearest else None,
            "Operator": nearest.get("Operator") if nearest else None,
            "DistanceKm": round(float(nearest_distance), 2) if nearest_distance is not None else None,
            "Score": round(score, 1),
            "FoundWithinRadius": bool(found),
        })
    return details, round(sum(d["Score"] for d in details) / len(details), 1) if details else None



def list_services_near_candidate_route(candidate, service_locations, selected_types, radius_km, max_results=200):
    """Return the nearest-to-route selected service records, sorted by proximity.

    Distances are straight-line distance to sampled route geometry (not driving detours).
    A cap keeps the page responsive when a wide corridor contains many records; the total
    matching count is returned separately so the UI can disclose when results are capped.
    """
    geometry = candidate.get("geometry") or {}
    coords = _sample_route_coords(geometry)
    segments, projection = _project_route_for_distance(coords)
    if not segments or projection is None or not selected_types:
        return [], 0

    allowed = set(selected_types)
    matches = []
    radius = float(radius_km)
    for service in service_locations:
        if service.get("LocationType") not in allowed:
            continue
        try:
            lat = float(service.get("Latitude"))
            lon = float(service.get("Longitude"))
        except (TypeError, ValueError):
            continue
        distance = _point_to_segments_distance_km(
            {"Latitude": lat, "Longitude": lon}, segments, projection
        )
        if distance is None or distance > radius:
            continue
        matches.append({
            "ServiceLocationID": service.get("ServiceLocationID"),
            "OSM_ID": service.get("OSM_ID"),
            "Name": service.get("Name"),
            "Label": SERVICE_TYPE_LABELS.get(
                service.get("LocationType"),
                str(service.get("LocationType") or "service").replace("_", " ").title(),
            ),
            "LocationType": service.get("LocationType"),
            "Address": service.get("Address"),
            "Latitude": lat,
            "Longitude": lon,
            "Operator": service.get("Operator"),
            "Brand": service.get("Brand"),
            "Postcode": service.get("Postcode"),
            "DistanceKm": round(float(distance), 3),
        })

    matches.sort(key=lambda item: (item["DistanceKm"], str(item.get("Label") or ""), str(item.get("Name") or "")))
    total_matches = len(matches)
    return matches[:max(0, int(max_results))], total_matches


def ai_route_score(distance_km, eta_hours, fuel_cost, preference, traffic_summary=None, service_score=None):
    """Explainable weighted decision score (rule-based, not a trained ML model)."""
    distance_score = max(0.0, 100.0 * (1.0 - min(max(distance_km, 0.0), 1500.0) / 1500.0))
    time_score = max(0.0, 100.0 * (1.0 - min(max(eta_hours, 0.0), 24.0) / 24.0))
    fuel_score = max(0.0, 100.0 * (1.0 - min(max(fuel_cost, 0.0), 5000.0) / 5000.0))
    factors = {"distance": distance_score, "time": time_score, "fuel": fuel_score}
    weights_by_preference = {
        "balanced": {"time": 0.30, "traffic": 0.30, "fuel": 0.25, "distance": 0.15},
        "time": {"time": 0.45, "traffic": 0.35, "fuel": 0.08, "distance": 0.12},
        "fuel": {"time": 0.18, "traffic": 0.17, "fuel": 0.50, "distance": 0.15},
    }
    weights = weights_by_preference.get(preference, weights_by_preference["balanced"]).copy()
    if service_score is not None:
        # Selected services become a meaningful factor while retaining time/fuel/traffic.
        service_weights = {
            "balanced": {"time": 0.22, "traffic": 0.18, "fuel": 0.18, "distance": 0.12, "services": 0.30},
            "time": {"time": 0.30, "traffic": 0.20, "fuel": 0.10, "distance": 0.10, "services": 0.30},
            "fuel": {"time": 0.15, "traffic": 0.12, "fuel": 0.35, "distance": 0.08, "services": 0.30},
        }
        weights = service_weights.get(preference, service_weights["balanced"]).copy()
        factors["services"] = float(service_score)
    if traffic_summary:
        factors["traffic"] = max(0.0, 100.0 - traffic_summary["congestion_pct"])
    else:
        weights.pop("traffic", None)
    weight_sum = sum(weights.values())
    score = sum(factors[name] * weight for name, weight in weights.items()) / weight_sum if weight_sum else 0.0
    if score >= 75:
        label = "Good on the current criteria"
    elif score >= 50:
        label = "Review the trade-offs"
    else:
        label = "Less suitable on the current criteria"
    explain = {
        "time": "Time priority: estimated journey duration receives the highest weight among the selected criteria.",
        "fuel": "Fuel priority: estimated fuel expense receives the highest weight among the selected criteria.",
        "balanced": "Balanced priority: estimated time, fuel expense, distance and available traffic are combined.",
    }.get(preference, "The score combines the available route factors.")
    if traffic_summary:
        explain += " Live congestion sampled along the route is included in the traffic factor."
    elif service_score is not None:
        explain += " Live traffic is unavailable; selected-service proximity is still included alongside time, fuel cost and distance."
    else:
        explain += " Live traffic is unavailable, so the score is computed from time, fuel cost and distance only."
    factors_with_labels = [
        {"name": "Estimated time", "score": round(time_score, 1)},
        {"name": "Fuel cost", "score": round(fuel_score, 1)},
        {"name": "Distance", "score": round(distance_score, 1)},
    ]
    if traffic_summary:
        factors_with_labels.append({"name": "Live traffic flow", "score": round(factors["traffic"], 1)})
    if service_score is not None:
        factors_with_labels.append({"name": "Selected-service proximity", "score": round(float(service_score), 1)})
        explain += " Selected service categories are weighted equally; each contributes according to the closest matching location's distance from the route."
    return round(score, 1), label, explain, factors_with_labels


def rank_route_options(candidates, preference, selected_services=False):
    """Rank candidate routes using explainable preference-weighted relative scores.

    If multiple alternatives are available, metric scores compare each route with the
    best value within this candidate set. Traffic is used for the ranking only when
    every candidate has valid live-flow observations, avoiding unfair missing-data bias.
    """
    if not candidates:
        return candidates

    if len(candidates) == 1:
        only = candidates[0]
        score_eta = only["TrafficAdjustedTime"] if only["TrafficAdjustedTime"] is not None else only["EstimatedTime"]
        score, label, _explanation, factors = ai_route_score(
            only["TotalDistance"], score_eta, only["FuelCost"], preference,
            traffic_summary=only["TrafficSummary"],
            service_score=only.get("ServiceScore") if selected_services else None,
        )
        only["RankScore"] = score
        only["RankFactors"] = factors
        only["RankLabel"] = label
        only["RankingBasis"] = "Only one route was returned by the routing service; no distinct alternative was available to compare."
        if selected_services and only.get("ServiceScore") is not None:
            only["RankingBasis"] += " The score also includes proximity to your selected service categories."
        only["TrafficUsedForRanking"] = bool(only["TrafficSummary"])
        return candidates

    complete_traffic = all(candidate.get("TrafficSummary") for candidate in candidates)
    if selected_services and all(candidate.get("ServiceScore") is not None for candidate in candidates):
        if preference == "time":
            weights = {"time": 0.36, "traffic": 0.20, "fuel": 0.10, "distance": 0.09, "services": 0.25}
        elif preference == "fuel":
            weights = {"time": 0.17, "traffic": 0.13, "fuel": 0.32, "distance": 0.13, "services": 0.25}
        else:
            weights = {"time": 0.24, "traffic": 0.18, "fuel": 0.20, "distance": 0.13, "services": 0.25}
        include_service_score = True
    else:
        if preference == "time":
            weights = {"time": 0.50, "traffic": 0.35, "fuel": 0.05, "distance": 0.10}
        elif preference == "fuel":
            weights = {"time": 0.15, "traffic": 0.15, "fuel": 0.55, "distance": 0.15}
        else:
            weights = {"time": 0.30, "traffic": 0.30, "fuel": 0.25, "distance": 0.15}
        include_service_score = False
    if not complete_traffic:
        weights.pop("traffic", None)

    time_values = [float(c["TrafficAdjustedTime"] if complete_traffic and c["TrafficAdjustedTime"] is not None else c["EstimatedTime"]) for c in candidates]
    fuel_values = [float(c["FuelCost"]) for c in candidates]
    distance_values = [float(c["TotalDistance"]) for c in candidates]
    min_time, min_fuel, min_distance = min(time_values), min(fuel_values), min(distance_values)

    def lower_is_better(value, minimum):
        if value <= 0:
            return 100.0 if minimum <= 0 else 0.0
        return max(0.0, min(100.0, 100.0 * minimum / value))

    for index, candidate in enumerate(candidates):
        time_score = lower_is_better(time_values[index], min_time)
        fuel_score = lower_is_better(fuel_values[index], min_fuel)
        distance_score = lower_is_better(distance_values[index], min_distance)
        factors = {"time": time_score, "fuel": fuel_score, "distance": distance_score}
        if include_service_score:
            factors["services"] = float(candidate.get("ServiceScore") or 0.0)
        if complete_traffic:
            traffic = candidate["TrafficSummary"]
            factors["traffic"] = 0.0 if traffic.get("road_closure") else max(0.0, 100.0 - float(traffic["congestion_pct"]))
        total_weight = sum(weights.values()) or 1.0
        score = sum(factors[name] * weight for name, weight in weights.items()) / total_weight
        factor_labels = [
            {"name": "Estimated time" + (" (traffic-adjusted)" if complete_traffic else ""), "score": round(time_score, 1)},
            {"name": "Fuel cost", "score": round(fuel_score, 1)},
            {"name": "Distance", "score": round(distance_score, 1)},
        ]
        if complete_traffic:
            factor_labels.append({"name": "Live traffic flow", "score": round(factors["traffic"], 1)})
        if include_service_score:
            factor_labels.append({"name": "Selected-service proximity", "score": round(factors["services"], 1)})
        candidate["RankScore"] = round(score, 1)
        candidate["RankFactors"] = factor_labels
        candidate["RankLabel"] = "Best among evaluated options" if score >= 99.9 else "Alternative option"
        candidate["TrafficUsedForRanking"] = complete_traffic
        candidate["RankingBasis"] = (
            "Compared candidate paths using your selected priority and selected-service proximity. Live traffic was included."
            if complete_traffic and include_service_score else
            "Compared candidate paths using your selected priority and selected-service proximity; live traffic was unavailable for every candidate and was excluded for fairness."
            if include_service_score else
            "Compared across the candidate paths using your selected priority. Live traffic was included."
            if complete_traffic else
            "Compared across candidate paths using estimated time, distance and fuel cost. Live traffic was not available for every path, so it was excluded from the ranking for fairness."
        )
    return candidates


@app.route("/routes", methods=["GET", "POST"])
def routes():
    cities = fetch_cities()
    result = None
    error = None
    route_geometry = None
    map_points = None
    map_routes = []
    map_notice = None
    route_notice = None
    route_options = []
    turn_by_turn = []
    nearby_services = []
    nearby_error = None
    traffic_summary = None
    traffic_message = None
    ai_score = None
    ai_score_label = None
    ai_explanation = None
    ai_score_factors = []
    source_id = request.values.get("source_city", type=int)
    destination_id = request.values.get("destination_city", type=int)
    mileage_value = request.values.get("mileage", default="15")
    fuel_price_value = request.values.get("fuel_price", default="100")
    preference = request.values.get("preference", default="balanced")
    service_radius_value = request.values.get("service_radius", default="10")
    allowed_service_types = {key for key, _label in SERVICE_TYPES}
    if request.method == "POST":
        selected_service_types = [value for value in request.form.getlist("service_types") if value in allowed_service_types]
    elif request.args.getlist("service_types"):
        selected_service_types = [value for value in request.args.getlist("service_types") if value in allowed_service_types]
    else:
        selected_service_types = ["hospital"]
    route_service_matches = []
    route_service_total_count = 0
    map_services = []
    route_service_locations = []
    service_scoring_enabled = False
    service_error = None

    if request.method == "POST":
        try:
            mileage = float(mileage_value)
            fuel_price = float(fuel_price_value)
            service_radius = float(service_radius_value)
            if mileage <= 0:
                raise ValueError("Mileage must be greater than zero.")
            if fuel_price < 0:
                raise ValueError("Fuel price cannot be negative.")
            if not 1 <= service_radius <= 100:
                raise ValueError("Nearby-service radius must be from 1 to 100 km.")
            if preference not in {"balanced", "time", "fuel"}:
                preference = "balanced"
            if not source_id or not destination_id:
                raise ValueError("Select both a source and destination.")
            if source_id == destination_id:
                raise ValueError("Source and destination must be different.")

            conn = get_connection()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    """SELECT SC.CityID AS SourceCityID, SC.CityName AS SourceCity,
                              SC.Latitude AS SourceLat, SC.Longitude AS SourceLon,
                              SS.StateName AS SourceState,
                              DC.CityID AS DestinationCityID, DC.CityName AS DestinationCity,
                              DC.Latitude AS DestinationLat, DC.Longitude AS DestinationLon,
                              SD.StateName AS DestinationState
                       FROM CITY SC
                       JOIN STATE SS ON SS.StateID = SC.StateID
                       JOIN CITY DC ON DC.CityID = %s
                       JOIN STATE SD ON SD.StateID = DC.StateID
                       WHERE SC.CityID = %s""",
                    (destination_id, source_id),
                )
                city_pair = cur.fetchone()
                if not city_pair:
                    raise ValueError("The selected source or destination could not be found.")

                cur.execute(
                    """SELECT R.RouteID, R.TotalDistance, R.EstimatedTime, R.SafetyScore
                       FROM ROUTE R
                       WHERE R.SourceCityID = %s AND R.DestinationCityID = %s
                       LIMIT 1""",
                    (source_id, destination_id),
                )
                stored_route = cur.fetchone()
            finally:
                conn.close()

            source_lat = city_pair["SourceLat"]
            source_lon = city_pair["SourceLon"]
            destination_lat = city_pair["DestinationLat"]
            destination_lon = city_pair["DestinationLon"]
            coords_available = all(value is not None for value in (source_lat, source_lon, destination_lat, destination_lon))
            osrm_routes = []

            if coords_available:
                try:
                    # OSRM can return the primary route plus up to two alternatives.
                    osrm_routes = get_osrm_routes(
                        float(source_lat), float(source_lon),
                        float(destination_lat), float(destination_lon),
                        alternative_count=2,
                    )
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                    if not stored_route:
                        raise ValueError(
                            "The online routing service could not return a road path for this pair. "
                            "Check your connection and try again."
                        ) from exc
                    map_notice = "Online path calculation is unavailable. The stored distance/time record is shown as a fallback, but turn-by-turn path geometry cannot be produced right now."
            elif not stored_route:
                raise ValueError("This city pair has no stored route and one or both places lack coordinates.")
            else:
                map_notice = "This pair has a stored distance/time record, but its city coordinates are missing, so a full road path cannot be drawn."

            # Use complete OSRM candidate paths when available; stored ROUTE rows are a fallback only.
            candidates = []
            if osrm_routes:
                for raw_route in osrm_routes:
                    distance_km = float(raw_route.get("distance") or 0.0) / 1000.0
                    eta_hours = float(raw_route.get("duration") or 0.0) / 3600.0
                    geometry = raw_route.get("geometry")
                    traffic, traffic_note = get_live_route_traffic(geometry, max_points=2)
                    adjusted_eta = eta_hours * traffic["delay_factor"] if traffic else None
                    candidates.append({
                        "TotalDistance": distance_km,
                        "EstimatedTime": eta_hours,
                        "FuelCost": (distance_km / mileage) * fuel_price,
                        "TrafficSummary": traffic,
                        "TrafficMessage": traffic_note,
                        "TrafficAdjustedTime": adjusted_eta,
                        "geometry": geometry,
                        "Directions": extract_turn_by_turn(raw_route),
                        "RouteSource": "Calculated road path using OSRM",
                        "SafetyScore": None,
                    })
                if len(candidates) == 1:
                    route_notice = "The routing service returned one usable route for this city pair. Alternative routes are not guaranteed to be available for every journey."
                else:
                    route_notice = f"Compared {len(candidates)} candidate road paths. The recommendation is based on the selected priority and available live traffic observations."
            else:
                # Keep existing stored-route functionality if the external route engine is unreachable.
                distance_km = float(stored_route["TotalDistance"] or 0.0)
                eta_hours = float(stored_route["EstimatedTime"] or 0.0)
                candidates.append({
                    "TotalDistance": distance_km,
                    "EstimatedTime": eta_hours,
                    "FuelCost": (distance_km / mileage) * fuel_price,
                    "TrafficSummary": None,
                    "TrafficMessage": "Online route geometry is unavailable; showing the stored database estimate.",
                    "TrafficAdjustedTime": None,
                    "geometry": None,
                    "Directions": [],
                    "RouteSource": "Stored TravelDB route (online path unavailable)",
                    "SafetyScore": stored_route.get("SafetyScore"),
                })

            if selected_service_types and any(candidate.get("geometry") for candidate in candidates):
                try:
                    route_service_locations = fetch_services_in_route_corridor(candidates, selected_service_types, service_radius)
                    for candidate in candidates:
                        details, score = score_route_service_proximity(
                            candidate, route_service_locations, selected_service_types, service_radius
                        )
                        candidate["ServiceProximity"] = details
                        candidate["ServiceScore"] = score
                    service_scoring_enabled = all(candidate.get("ServiceScore") is not None for candidate in candidates)
                except mysql.connector.Error as exc:
                    service_error = "Route was calculated, but route-aware service scoring could not query the database: " + str(exc)
                    for candidate in candidates:
                        candidate["ServiceProximity"] = []
                        candidate["ServiceScore"] = None
            else:
                for candidate in candidates:
                    candidate["ServiceProximity"] = []
                    candidate["ServiceScore"] = None
                if selected_service_types:
                    service_error = "Service-aware route scoring needs an online road path with geometry."

            candidates = rank_route_options(candidates, preference, selected_services=service_scoring_enabled)
            candidates.sort(key=lambda item: (-float(item["RankScore"]), float(item["EstimatedTime"])))
            for rank, candidate in enumerate(candidates, start=1):
                candidate["RouteRank"] = rank
                candidate["Title"] = "Recommended route" if rank == 1 else f"Alternative route {rank}"
                candidate["Recommended"] = rank == 1
                candidate["TrafficLabel"] = candidate["TrafficSummary"]["level"] if candidate.get("TrafficSummary") else "Not available"
                candidate["AdjustedETAHours"] = candidate["TrafficAdjustedTime"]
                candidate["ExtraMinutes"] = max(0.0, (candidate["TrafficAdjustedTime"] - candidate["EstimatedTime"]) * 60.0) if candidate["TrafficAdjustedTime"] is not None else None

            best = candidates[0]
            route_options = candidates
            route_geometry = best.get("geometry")
            traffic_summary = best.get("TrafficSummary")
            # Keep the summary fields expected by routes.html alongside the sampled
            # provider metrics. These are candidate-level values, so copy them into
            # the selected recommendation's traffic summary before rendering.
            if traffic_summary:
                traffic_summary["adjusted_eta_hours"] = best.get("TrafficAdjustedTime")
                traffic_summary["extra_minutes"] = best.get("ExtraMinutes", 0.0)
            traffic_message = best.get("TrafficMessage")
            turn_by_turn = best.get("Directions") or []
            if not route_geometry:
                map_notice = map_notice or "Full road geometry is not currently available, so the turn list/map cannot be shown for the fallback estimate."
            elif not turn_by_turn:
                map_notice = map_notice or "The route line is available, but the routing service did not return detailed turn instructions for this path."

            result = {
                "RouteID": None,
                "RouteRank": best["RouteRank"],
                "RouteCount": len(candidates),
                "SourceCity": city_pair["SourceCity"],
                "DestinationCity": city_pair["DestinationCity"],
                "TotalDistance": best["TotalDistance"],
                "EstimatedTime": best["EstimatedTime"],
                "SafetyScore": best.get("SafetyScore"),
                "FuelCost": best["FuelCost"],
                "Mileage": mileage,
                "FuelPrice": fuel_price,
                "Preference": preference,
                "RouteSource": best["RouteSource"],
                "AIScore": best["RankScore"],
                "TrafficAdjustedTime": best["TrafficAdjustedTime"],
            }

            _calculated_score, calculated_label, ai_explanation, calculated_factors = ai_route_score(
                best["TotalDistance"],
                best["TrafficAdjustedTime"] if best["TrafficAdjustedTime"] is not None else best["EstimatedTime"],
                best["FuelCost"], preference,
                traffic_summary=traffic_summary,
                service_score=best.get("ServiceScore") if service_scoring_enabled else None,
            )
            # Display the same final comparison score used to rank route cards.
            ai_score = best["RankScore"]
            ai_score_label = "Highest-ranked among evaluated route options" if len(candidates) > 1 else calculated_label
            ai_score_factors = best.get("RankFactors") or calculated_factors
            result["AIScore"] = best["RankScore"]
            result["Recommendation"] = (
                f"Take Recommended Route 1 of {len(candidates)}. It received the highest score for your "
                f"{ {'balanced': 'balanced', 'time': 'time-focused', 'fuel': 'fuel-cost-focused'}.get(preference, 'balanced') } priority "
                f"({best['RankScore']:.1f}/100 among the evaluated options). Follow the turn-by-turn path below."
            )
            if service_scoring_enabled:
                selected_labels = ", ".join(SERVICE_TYPE_LABELS.get(item, item) for item in selected_service_types)
                result["Recommendation"] += (
                    f" Service-aware ranking considered {selected_labels}; the selected route's service proximity score is "
                    f"{float(best.get('ServiceScore') or 0):.1f}/100 based on the closest matching location for each selected category "
                    f"within {service_radius:g} km of the road path."
                )
            if service_error:
                result["Recommendation"] += " Service-aware ranking was unavailable: " + service_error
            if not best.get("TrafficUsedForRanking") and len(candidates) > 1:
                result["Recommendation"] += " Live traffic was not used to rank every candidate because complete traffic observations were not available for all of them."

            if coords_available:
                map_points = {
                    "source": {"name": city_pair["SourceCity"], "lat": float(source_lat), "lon": float(source_lon)},
                    "destination": {"name": city_pair["DestinationCity"], "lat": float(destination_lat), "lon": float(destination_lon)},
                }
                map_routes = [
                    {
                        "RouteRank": c["RouteRank"],
                        "Title": c["Title"],
                        "Recommended": c["Recommended"],
                        "RankScore": c["RankScore"],
                        "TotalDistance": float(c.get("TotalDistance") or 0.0),
                        "EstimatedTime": float(c.get("EstimatedTime") or 0.0),
                        "FuelCost": float(c.get("FuelCost") or 0.0),
                        "durationSeconds": float(c.get("EstimatedTime") or 0.0) * 3600.0,
                        "geometry": c.get("geometry"),
                        # Maneuver coordinates enable in-map directional markers.
                        "Directions": c.get("Directions") or [],
                    }
                    for c in candidates if c.get("geometry")
                ]

                # Restore the complete named nearby-service list (not just one nearest service per category).
                # These records are sorted by straight-line distance to the recommended path.
                if selected_service_types and best.get("geometry") and route_service_locations:
                    route_service_matches, route_service_total_count = list_services_near_candidate_route(
                        best, route_service_locations, selected_service_types, service_radius, max_results=200
                    )
                else:
                    route_service_matches, route_service_total_count = [], 0

                # Stable category-based codes are shared by the map marker and list row.
                # Counters follow nearest-to-route order within each category.
                marker_prefixes = {
                    "hospital": "H",
                    "ev_station": "EV",
                    "restaurant": "R",
                    "petrol_pump": "P",
                    "hotel": "HT",
                }
                marker_counts = {}
                for service_item in route_service_matches:
                    service_type = str(service_item.get("LocationType") or "")
                    marker_counts[service_type] = marker_counts.get(service_type, 0) + 1
                    service_item["MapCode"] = (
                        marker_prefixes.get(service_type, "S") + str(marker_counts[service_type])
                    )

                map_services = [
                    {"id": item.get("ServiceLocationID"),
                     "name": item.get("Name") or "Unnamed service", "label": item.get("Label"),
                     "location_type": item.get("LocationType"), "marker_code": item.get("MapCode"),
                     "lat": item.get("Latitude"), "lon": item.get("Longitude"),
                     "distance_km": item.get("DistanceKm"), "address": item.get("Address"),
                     "brand": item.get("Brand"), "operator": item.get("Operator")}
                    for item in route_service_matches
                    if item.get("Latitude") is not None and item.get("Longitude") is not None
                ]
                if selected_service_types and not route_service_total_count and not service_error:
                    nearby_error = f"No selected service type was found within {service_radius:g} km of the evaluated road path. Try a larger radius or fewer selected categories."
            else:
                nearby_error = "Route-aware service search requires source/destination coordinates and a road path."

        except (ValueError, InvalidOperation) as exc:
            error = str(exc)
        except mysql.connector.Error as exc:
            error = "Database query failed: " + str(exc)

    return render_template(
        "routes.html", cities=cities, result=result, error=error,
        source_id=source_id, destination_id=destination_id,
        mileage_value=mileage_value, fuel_price_value=fuel_price_value,
        preference=preference, selected_service_types=selected_service_types,
        service_radius_value=service_radius_value, service_types=SERVICE_TYPES,
        route_service_matches=route_service_matches, route_service_total_count=route_service_total_count, map_services=map_services,
        service_error=service_error,
        route_geometry=route_geometry, map_points=map_points, map_routes=map_routes,
        map_notice=map_notice, route_notice=route_notice, route_options=route_options,
        turn_by_turn=turn_by_turn, nearby_services=nearby_services, nearby_error=nearby_error,
        traffic_summary=traffic_summary, traffic_message=traffic_message,
        ai_score=ai_score, ai_score_label=ai_score_label,
        ai_explanation=ai_explanation, ai_score_factors=ai_score_factors,
        tomtom_configured=bool(TOMTOM_API_KEY),
    )

@app.route("/services", methods=["GET"])
def services():
    cities = fetch_cities()
    city_id = request.args.get("city_id", type=int)
    service_type = request.args.get("service_type", "hospital")
    radius_value = request.args.get("radius", default="10")
    results = []
    origin = None
    error = None

    allowed_types = {key for key, _label in SERVICE_TYPES}
    if service_type not in allowed_types:
        service_type = "hospital"

    if city_id:
        try:
            radius = float(radius_value)
            if not 1 <= radius <= 100:
                raise ValueError("Radius must be from 1 to 100 km.")
            conn = get_connection()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT CityID, CityName, Latitude, Longitude FROM CITY WHERE CityID = %s",
                    (city_id,),
                )
                origin = cur.fetchone()
                if not origin:
                    raise ValueError("Selected city was not found.")
                if origin["Latitude"] is None or origin["Longitude"] is None:
                    raise ValueError("This city does not have coordinates in the database.")
                lat = float(origin["Latitude"])
                lon = float(origin["Longitude"])
                cur.execute(
                    """SELECT S.ServiceLocationID, S.Name, S.LocationType, S.Address,
                              S.Latitude, S.Longitude, S.Operator, S.Brand,
                              (6371 * ACOS(LEAST(1.0, GREATEST(-1.0,
                                COS(RADIANS(%s)) * COS(RADIANS(S.Latitude)) *
                                COS(RADIANS(S.Longitude) - RADIANS(%s)) +
                                SIN(RADIANS(%s)) * SIN(RADIANS(S.Latitude))
                              )))) AS DistanceKm
                       FROM SERVICE_LOCATION S
                       WHERE S.LocationType = %s
                         AND S.Latitude IS NOT NULL AND S.Longitude IS NOT NULL
                       HAVING DistanceKm <= %s
                       ORDER BY DistanceKm
                       LIMIT 100""",
                    (lat, lon, lat, service_type, radius),
                )
                results = cur.fetchall()
            finally:
                conn.close()
        except (ValueError, InvalidOperation) as exc:
            error = str(exc)
        except mysql.connector.Error as exc:
            error = "Database query failed: " + str(exc)

    return render_template(
        "services.html", cities=cities, city_id=city_id,
        service_type=service_type, radius_value=radius_value,
        service_types=SERVICE_TYPES, results=results, origin=origin, error=error,
    )


@app.route("/plans", methods=["GET", "POST"])
def plans():
    cities = fetch_cities()
    if request.method == "POST":
        name = request.form.get("plan_name", "").strip()
        source_id = request.form.get("source_city", type=int)
        destination_id = request.form.get("destination_city", type=int)
        travel_mode = request.form.get("travel_mode", "Car")
        notes = request.form.get("notes", "").strip() or None
        if not name:
            flash("Plan name is required.", "error")
        elif not source_id or not destination_id:
            flash("Choose both source and destination.", "error")
        elif source_id == destination_id:
            flash("Source and destination must be different.", "error")
        elif travel_mode not in TRAVEL_MODES:
            flash("Choose a valid travel mode.", "error")
        else:
            conn = None
            try:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO SAVED_TRIP_PLAN
                       (PlanName, SourceCityID, DestinationCityID, TravelMode, Notes)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (name, source_id, destination_id, travel_mode, notes),
                )
                conn.commit()
                flash("Trip plan saved to MySQL.", "success")
                return redirect(url_for("plans"))
            except mysql.connector.Error as exc:
                if conn:
                    conn.rollback()
                flash("Could not save plan: " + str(exc), "error")
            finally:
                if conn and conn.is_connected():
                    conn.close()

    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """SELECT P.PlanID, P.PlanName, P.SourceCityID, P.DestinationCityID,
                      P.TravelMode, P.Notes, P.CreatedAt,
                      SC.CityName AS SourceCity, DC.CityName AS DestinationCity
               FROM SAVED_TRIP_PLAN P
               JOIN CITY SC ON SC.CityID = P.SourceCityID
               JOIN CITY DC ON DC.CityID = P.DestinationCityID
               ORDER BY P.CreatedAt DESC, P.PlanID DESC"""
        )
        saved_plans = cur.fetchall()
    finally:
        conn.close()

    return render_template("plans.html", cities=cities, plans=saved_plans, travel_modes=TRAVEL_MODES)


@app.route("/plans/<int:plan_id>/edit", methods=["GET", "POST"])
def edit_plan(plan_id):
    cities = fetch_cities()
    plan = fetch_plan(plan_id)
    if not plan:
        flash("Plan not found.", "error")
        return redirect(url_for("plans"))

    if request.method == "POST":
        name = request.form.get("plan_name", "").strip()
        source_id = request.form.get("source_city", type=int)
        destination_id = request.form.get("destination_city", type=int)
        travel_mode = request.form.get("travel_mode", "Car")
        notes = request.form.get("notes", "").strip() or None
        if not name:
            flash("Plan name is required.", "error")
        elif not source_id or not destination_id or source_id == destination_id:
            flash("Choose two different cities.", "error")
        elif travel_mode not in TRAVEL_MODES:
            flash("Choose a valid travel mode.", "error")
        else:
            conn = None
            try:
                conn = get_connection()
                cur = conn.cursor()
                cur.execute(
                    """UPDATE SAVED_TRIP_PLAN
                       SET PlanName = %s, SourceCityID = %s, DestinationCityID = %s,
                           TravelMode = %s, Notes = %s
                       WHERE PlanID = %s""",
                    (name, source_id, destination_id, travel_mode, notes, plan_id),
                )
                conn.commit()
                flash("Trip plan updated in MySQL.", "success")
                return redirect(url_for("plans"))
            except mysql.connector.Error as exc:
                if conn:
                    conn.rollback()
                flash("Could not update plan: " + str(exc), "error")
            finally:
                if conn and conn.is_connected():
                    conn.close()
        plan.update({
            "PlanName": name,
            "SourceCityID": source_id,
            "DestinationCityID": destination_id,
            "TravelMode": travel_mode,
            "Notes": notes or "",
        })

    return render_template("edit_plan.html", plan=plan, cities=cities, travel_modes=TRAVEL_MODES)


@app.route("/plans/<int:plan_id>/delete", methods=["POST"])
def delete_plan(plan_id):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM SAVED_TRIP_PLAN WHERE PlanID = %s", (plan_id,))
        conn.commit()
        if cur.rowcount:
            flash("Trip plan deleted from MySQL.", "success")
        else:
            flash("Plan not found.", "error")
    except mysql.connector.Error as exc:
        if conn:
            conn.rollback()
        flash("Could not delete plan: " + str(exc), "error")
    finally:
        if conn and conn.is_connected():
            conn.close()
    return redirect(url_for("plans"))


@app.errorhandler(mysql.connector.Error)
def handle_db_error(exc):
    return render_template("error.html", message=str(exc)), 500


if __name__ == "__main__":
    # Run only on your own computer for the project demonstration.
    app.run(host="127.0.0.1", port=5000, debug=True)
