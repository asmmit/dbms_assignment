"""
TravelDB — MongoDB Atlas Index Management
Creates and validates the required spatial (2dsphere) and compound indexes
as specified in the DA3 project design (Table 3.9).
"""

import sys
from pymongo import ASCENDING, DESCENDING, GEOSPHERE
from mongo_db import get_mongo_db, check_mongo_connection


def create_all_indexes(recreate=False):
    """
    Creates indexes across service_places, trips, and traffic_snapshots collections.
    """
    ok, info, err = check_mongo_connection()
    if not ok:
        print(f"Error connecting to MongoDB: {err}")
        return False

    db = get_mongo_db()
    results = {}

    print("--- 1. Creating indexes on 'service_places' ---")
    sp = db["service_places"]
    if recreate:
        # Drop existing non-_id indexes
        for idx in sp.list_indexes():
            if idx["name"] != "_id_":
                sp.drop_index(idx["name"])
                print(f"  Dropped index: {idx['name']}")

    # 1. 2dsphere spatial index on GeoJSON location
    idx_geo = sp.create_index([("location", GEOSPHERE)], name="idx_service_location_2dsphere")
    print(f"  Created 2dsphere index: {idx_geo}")

    # 2. Compound index on (category, rating desc) for best-rated places
    idx_cat_rating = sp.create_index([("category", ASCENDING), ("rating", DESCENDING)], name="idx_category_rating")
    print(f"  Created compound index: {idx_cat_rating}")

    # 3. Compound index on (category, name)
    idx_cat_name = sp.create_index([("category", ASCENDING), ("name", ASCENDING)], name="idx_category_name")
    print(f"  Created compound index: {idx_cat_name}")

    # 4. Unique or lookup index on serviceLocationId
    idx_sec_id = sp.create_index([("serviceLocationId", ASCENDING)], unique=True, name="idx_service_location_id_unique")
    print(f"  Created unique index: {idx_sec_id}")

    results["service_places"] = list(sp.index_information().keys())

    print("\n--- 2. Creating indexes on 'trips' ---")
    trips = db["trips"]
    if recreate:
        for idx in trips.list_indexes():
            if idx["name"] != "_id_":
                trips.drop_index(idx["name"])
                print(f"  Dropped index: {idx['name']}")

    # 1. User trip history (newest first)
    idx_user_time = trips.create_index([("userId", ASCENDING), ("startTime", DESCENDING)], name="idx_trips_user_time")
    print(f"  Created index: {idx_user_time}")

    # 2. Route lookup
    idx_route = trips.create_index([("routeId", ASCENDING)], name="idx_trips_route")
    print(f"  Created index: {idx_route}")

    results["trips"] = list(trips.index_information().keys())

    print("\n--- 3. Creating indexes on 'traffic_snapshots' ---")
    traffic = db["traffic_snapshots"]
    if recreate:
        for idx in traffic.list_indexes():
            if idx["name"] != "_id_":
                traffic.drop_index(idx["name"])
                print(f"  Dropped index: {idx['name']}")

    # 1. Latest snapshot for segment
    idx_seg_time = traffic.create_index([("segmentOsmId", ASCENDING), ("timestamp", DESCENDING)], name="idx_traffic_seg_time")
    print(f"  Created index: {idx_seg_time}")

    # 2. Aggregation support on roadType and congestion
    idx_road_cong = traffic.create_index([("roadType", ASCENDING), ("congestion", ASCENDING)], name="idx_traffic_road_congestion")
    print(f"  Created index: {idx_road_cong}")

    results["traffic_snapshots"] = list(traffic.index_information().keys())

    print("\nIndex verification summary:")
    for col, idx_list in results.items():
        print(f"  {col}: {idx_list}")

    return True


def list_existing_indexes():
    """Lists existing indexes across the three collections."""
    db = get_mongo_db()
    for col_name in ["service_places", "trips", "traffic_snapshots"]:
        col = db[col_name]
        print(f"\nCollection '{col_name}' indexes:")
        for name, info in col.index_information().items():
            print(f"  - {name}: key={info['key']}")


if __name__ == "__main__":
    recreate_flag = "--recreate" in sys.argv
    create_all_indexes(recreate=recreate_flag)
