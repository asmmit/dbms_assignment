"""
TravelDB — MongoDB Atlas CRUD Operations
Provides complete Create, Read, Update, and Delete operations for:
1. 'trips' (denormalized trip documents with embedded stops).
2. 'service_places' (spatial queries and category searches).
3. 'traffic_snapshots' (time-series traffic observations).
"""

from datetime import datetime
from bson import ObjectId
from pymongo.errors import PyMongoError
from mongo_db import get_mongo_db


# ---------------------------------------------------------------------------
# 1. TRIPS CRUD
# ---------------------------------------------------------------------------

def create_trip(user_id, source_city, destination_city, route_id=None,
                vehicle_id=None, stops=None, total_distance=0.0,
                estimated_time=0.0, fuel_cost=0.0, travel_score=None,
                notes=""):
    """
    Creates a new trip document in MongoDB with an embedded list of stops.
    Document model represents complete journey context without needing SQL joins.
    """
    db = get_mongo_db()
    trips_col = db["trips"]
    
    trip_doc = {
        "userId": int(user_id),
        "vehicleId": int(vehicle_id) if vehicle_id is not None else None,
        "routeId": int(route_id) if route_id is not None else None,
        "sourceCity": source_city,
        "destinationCity": destination_city,
        "stops": stops or [],  # Embedded list of dicts: {name, category, location, arrivalEstimate}
        "totals": {
            "totalDistanceKm": float(total_distance),
            "estimatedTimeHours": float(estimated_time),
            "fuelCostInr": float(fuel_cost),
        },
        "travelScore": float(travel_score) if travel_score is not None else None,
        "status": "planned",
        "notes": notes,
        "startTime": datetime.now(),
        "endTime": None,
        "createdAt": datetime.now(),
        "updatedAt": datetime.now(),
    }
    
    result = trips_col.insert_one(trip_doc)
    trip_doc["_id"] = result.inserted_id
    return trip_doc


def get_trip(trip_id):
    """Retrieves a trip document by ObjectId or string representation."""
    db = get_mongo_db()
    trips_col = db["trips"]
    _id = ObjectId(trip_id) if isinstance(trip_id, str) else trip_id
    return trips_col.find_one({"_id": _id})


def list_user_trips(user_id, limit=20):
    """
    Lists trips for a given user sorted newest first.
    Utilizes the compound index idx_trips_user_time (userId, startTime desc).
    """
    db = get_mongo_db()
    trips_col = db["trips"]
    return list(trips_col.find({"userId": int(user_id)}).sort("startTime", -1).limit(limit))


def update_trip(trip_id, update_fields):
    """
    Updates specified fields on an existing trip document.
    Automatically maintains updatedAt timestamp.
    """
    db = get_mongo_db()
    trips_col = db["trips"]
    _id = ObjectId(trip_id) if isinstance(trip_id, str) else trip_id
    
    fields = dict(update_fields)
    fields["updatedAt"] = datetime.now()
    
    result = trips_col.update_one({"_id": _id}, {"$set": fields})
    return result.modified_count > 0


def add_stop_to_trip(trip_id, stop_name, category, lon, lat, arrival_estimate=None):
    """Appends an intermediate stop to a trip's embedded stops array."""
    db = get_mongo_db()
    trips_col = db["trips"]
    _id = ObjectId(trip_id) if isinstance(trip_id, str) else trip_id
    
    stop_doc = {
        "name": stop_name,
        "category": category,
        "location": {
            "type": "Point",
            "coordinates": [float(lon), float(lat)],
        },
        "arrivalEstimate": arrival_estimate,
        "addedAt": datetime.now(),
    }
    
    result = trips_col.update_one(
        {"_id": _id},
        {
            "$push": {"stops": stop_doc},
            "$set": {"updatedAt": datetime.now()}
        }
    )
    return result.modified_count > 0


def delete_trip(trip_id):
    """Deletes a trip document from MongoDB."""
    db = get_mongo_db()
    trips_col = db["trips"]
    _id = ObjectId(trip_id) if isinstance(trip_id, str) else trip_id
    result = trips_col.delete_one({"_id": _id})
    return result.deleted_count > 0


# ---------------------------------------------------------------------------
# 2. SERVICE PLACES CRUD & SPATIAL QUERIES
# ---------------------------------------------------------------------------

def find_places_near(lon, lat, max_distance_meters=10000, category=None, limit=20):
    """
    Performs a native MongoDB 2dsphere $near query for places within radius.
    Orders results strictly by proximity using spherical geometry calculations.
    """
    db = get_mongo_db()
    col = db["service_places"]
    
    query = {
        "location": {
            "$near": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [float(lon), float(lat)]
                },
                "$maxDistance": int(max_distance_meters)
            }
        }
    }
    if category:
        query["category"] = category.lower()
        
    return list(col.find(query).limit(limit))


def find_places_in_bbox(min_lon, min_lat, max_lon, max_lat, category=None, limit=100):
    """
    Performs a $geoWithin query using a bounding box polygon.
    """
    db = get_mongo_db()
    col = db["service_places"]
    
    query = {
        "location": {
            "$geoWithin": {
                "$box": [
                    [float(min_lon), float(min_lat)],
                    [float(max_lon), float(max_lat)]
                ]
            }
        }
    }
    if category:
        query["category"] = category.lower()
        
    return list(col.find(query).limit(limit))


def find_best_rated_places(category, limit=10):
    """
    Finds top-rated places in a category.
    Utilizes compound index (category: 1, rating: -1).
    """
    db = get_mongo_db()
    col = db["service_places"]
    query = {"category": category.lower(), "rating": {"$ne": None}}
    return list(col.find(query).sort("rating", -1).limit(limit))


# ---------------------------------------------------------------------------
# 3. TRAFFIC SNAPSHOTS CRUD
# ---------------------------------------------------------------------------

def record_traffic_snapshot(segment_osm_id, current_speed, free_flow_speed,
                            road_type="primary", road_name="", timestamp=None):
    """
    Records a traffic observation into the traffic_snapshots time-series collection.
    Congestion is computed deterministically as (1 - current/freeFlow) * 100.
    """
    db = get_mongo_db()
    col = db["traffic_snapshots"]
    
    cur_spd = float(current_speed)
    free_spd = float(free_flow_speed)
    ratio = cur_spd / free_spd if free_spd > 0 else 1.0
    congestion = max(0.0, min(100.0, (1.0 - ratio) * 100.0))
    
    doc = {
        "segmentOsmId": int(segment_osm_id),
        "roadName": road_name,
        "roadType": road_type,
        "currentSpeed": cur_spd,
        "freeFlowSpeed": free_spd,
        "congestion": round(congestion, 2),
        "timestamp": timestamp or datetime.now(),
    }
    result = col.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_latest_traffic_snapshot(segment_osm_id):
    """
    Fetches the latest recorded traffic snapshot for a given segment OSM ID.
    Utilizes compound index (segmentOsmId: 1, timestamp: -1).
    """
    db = get_mongo_db()
    col = db["traffic_snapshots"]
    return col.find_one({"segmentOsmId": int(segment_osm_id)}, sort=[("timestamp", -1)])
