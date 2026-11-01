"""
TravelDB — MongoDB Aggregation Pipelines
Implements multi-stage aggregation pipelines for TravelDB analytics
as specified in Appendix C.4 and Table 4.11.
"""

from mongo_db import get_mongo_db, check_mongo_connection


def aggregate_traffic_by_road_type():
    """
    Appendix C.4 pipeline:
    Calculates average congestion level and observation count grouped by road type.
    Equivalent to SQL:
        SELECT RoadType, AVG(CongestionLevel) AS avgCongestion, COUNT(*) AS n
        FROM TRAFFIC_RECORD JOIN ROAD_SEGMENT ... GROUP BY RoadType
    """
    db = get_mongo_db()
    col = db["traffic_snapshots"]
    
    pipeline = [
        {
            "$group": {
                "_id": "$roadType",
                "avgCongestion": {"$avg": "$congestion"},
                "observationCount": {"$sum": 1},
                "minCongestion": {"$min": "$congestion"},
                "maxCongestion": {"$max": "$congestion"},
            }
        },
        {"$sort": {"avgCongestion": -1}},
        {
            "$project": {
                "_id": 0,
                "roadType": "$_id",
                "avgCongestion": {"$round": ["$avgCongestion", 2]},
                "observationCount": 1,
                "minCongestion": 1,
                "maxCongestion": 1,
            }
        }
    ]
    return list(col.aggregate(pipeline))


def aggregate_places_by_category():
    """
    Calculates total locations, places with ratings, and average rating per service category.
    """
    db = get_mongo_db()
    col = db["service_places"]
    
    pipeline = [
        {
            "$group": {
                "_id": "$category",
                "totalPlaces": {"$sum": 1},
                "ratedPlaces": {
                    "$sum": {"$cond": [{"$ne": ["$rating", None]}, 1, 0]}
                },
                "avgRating": {"$avg": "$rating"},
                "withBrand": {
                    "$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$brand", ""]}}, 0]}, 1, 0]}
                },
                "withOperator": {
                    "$sum": {"$cond": [{"$gt": [{"$strLenCP": {"$ifNull": ["$operator", ""]}}, 0]}, 1, 0]}
                }
            }
        },
        {"$sort": {"totalPlaces": -1}},
        {
            "$project": {
                "_id": 0,
                "category": "$_id",
                "totalPlaces": 1,
                "ratedPlaces": 1,
                "avgRating": {"$round": ["$avgRating", 2]},
                "withBrand": 1,
                "withOperator": 1,
            }
        }
    ]
    return list(col.aggregate(pipeline))


def aggregate_top_fuel_brands(limit=10):
    """
    Finds top fuel station brands and their station counts.
    """
    db = get_mongo_db()
    col = db["service_places"]
    
    pipeline = [
        {"$match": {"category": "petrol_pump", "brand": {"$ne": "", "$exists": True}}},
        {"$group": {"_id": "$brand", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "brand": "$_id", "stationCount": "$count"}}
    ]
    return list(col.aggregate(pipeline))


def aggregate_trip_statistics():
    """
    Aggregates trip analytics: popular corridors, average distance, total distance.
    """
    db = get_mongo_db()
    col = db["trips"]
    
    pipeline = [
        {
            "$group": {
                "_id": {
                    "source": "$sourceCity",
                    "destination": "$destinationCity"
                },
                "tripCount": {"$sum": 1},
                "avgDistance": {"$avg": "$totals.totalDistanceKm"},
                "avgFuelCost": {"$avg": "$totals.fuelCostInr"},
                "avgScore": {"$avg": "$travelScore"},
            }
        },
        {"$sort": {"tripCount": -1}},
        {
            "$project": {
                "_id": 0,
                "corridor": {"$concat": ["$_id.source", " -> ", "$_id.destination"]},
                "tripCount": 1,
                "avgDistance": {"$round": ["$avgDistance", 1]},
                "avgFuelCost": {"$round": ["$avgFuelCost", 1]},
                "avgScore": {"$round": ["$avgScore", 1]},
            }
        }
    ]
    return list(col.aggregate(pipeline))


if __name__ == "__main__":
    ok, info, err = check_mongo_connection()
    if not ok:
        print(f"MongoDB not connected: {err}")
    else:
        print("=== Category Distribution in MongoDB Atlas ===")
        categories = aggregate_places_by_category()
        for cat in categories:
            print(f"  {cat['category']:<15} Total: {cat['totalPlaces']:<6} Avg Rating: {cat.get('avgRating', 'N/A')}")
        
        print("\n=== Top Petrol Pump Brands ===")
        brands = aggregate_top_fuel_brands()
        for b in brands:
            print(f"  {b['brand']:<25} Count: {b['stationCount']}")
