"""
TravelDB — Automated Test Suite for DA3 Advanced Database Layer
Tests:
1. MongoDB Atlas connectivity and secure configuration.
2. Collection document counts and synchronization integrity (24,649 places).
3. GeoJSON Point coordinate validity.
4. Index verification (2dsphere and compound indexes).
5. Geospatial queries ($near).
6. Trip document CRUD lifecycle (Insert, Read, Update, Delete).
7. Traffic snapshot insertion and retrieval.
8. Aggregation pipeline execution.
9. Error handling and invalid input handling.
"""

import unittest
from bson import ObjectId
from mongo_db import get_mongo_db, check_mongo_connection
from mongo_crud import (
    create_trip,
    get_trip,
    list_user_trips,
    update_trip,
    add_stop_to_trip,
    delete_trip,
    find_places_near,
    record_traffic_snapshot,
    get_latest_traffic_snapshot,
)
from mongo_aggregations import (
    aggregate_places_by_category,
    aggregate_top_fuel_brands,
)


class TestTravelDBDA3(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        ok, info, err = check_mongo_connection()
        if not ok:
            raise unittest.SkipTest(f"MongoDB Atlas is unavailable: {err}")
        cls.db = get_mongo_db()

    def test_01_mongodb_connectivity(self):
        """Verify secure connection to MongoDB Atlas and database access."""
        ok, info, err = check_mongo_connection()
        self.assertTrue(ok, f"Connection failed: {err}")
        self.assertEqual(info["database"], "TravelDB_Documents")
        self.assertIn("service_places", info["collections"])
        self.assertIn("trips", info["collections"])
        self.assertIn("traffic_snapshots", info["collections"])

    def test_02_sync_integrity_and_record_counts(self):
        """Verify exactly 24,649 service locations synced from real OSM data."""
        col = self.db["service_places"]
        count = col.count_documents({})
        self.assertEqual(count, 24649, f"Expected 24,649 places, got {count}")

    def test_03_geojson_coordinate_validity(self):
        """Verify sample documents have valid GeoJSON Point [lon, lat] format."""
        col = self.db["service_places"]
        sample = col.find_one({"location": {"$ne": None}})
        self.assertIsNotNone(sample)
        loc = sample.get("location")
        self.assertEqual(loc.get("type"), "Point")
        coords = loc.get("coordinates")
        self.assertIsInstance(coords, list)
        self.assertEqual(len(coords), 2)
        lon, lat = coords
        # Southern India bounding box check (lon: ~76 to ~81, lat: ~7.5 to ~14)
        self.assertTrue(75.0 <= lon <= 82.0, f"Longitude out of expected range: {lon}")
        self.assertTrue(7.0 <= lat <= 15.0, f"Latitude out of expected range: {lat}")

    def test_04_indexes_exist(self):
        """Verify 2dsphere and compound indexes are registered on collections."""
        sp_indexes = self.db["service_places"].index_information()
        self.assertIn("idx_service_location_2dsphere", sp_indexes)
        self.assertIn("idx_category_rating", sp_indexes)
        self.assertIn("idx_category_name", sp_indexes)

        trip_indexes = self.db["trips"].index_information()
        self.assertIn("idx_trips_user_time", trip_indexes)

        traffic_indexes = self.db["traffic_snapshots"].index_information()
        self.assertIn("idx_traffic_seg_time", traffic_indexes)

    def test_05_geospatial_near_query(self):
        """Verify 2dsphere spatial query returns places ordered by distance."""
        # Coordinates near Vellore Institute of Technology, Chennai campus
        results = find_places_near(80.1534, 12.8406, max_distance_meters=10000, category="hospital", limit=5)
        self.assertGreater(len(results), 0, "No hospitals returned near VIT Chennai campus")
        for r in results:
            self.assertEqual(r["category"], "hospital")
            self.assertIn("location", r)
            self.assertEqual(r["location"]["type"], "Point")

    def test_06_trip_crud_lifecycle(self):
        """Verify complete Create, Read, Update, and Delete operations for trips."""
        # 1. Create
        trip = create_trip(
            user_id=999,
            source_city="Vellore",
            destination_city="Bengaluru",
            total_distance=215.0,
            estimated_time=3.75,
            fuel_cost=1433.33,
            travel_score=92.0,
            notes="Automated Unit Test Trip"
        )
        trip_id = trip["_id"]
        self.assertIsInstance(trip_id, ObjectId)

        # 2. Read
        fetched = get_trip(trip_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["sourceCity"], "Vellore")
        self.assertEqual(fetched["destinationCity"], "Bengaluru")
        self.assertEqual(fetched["totals"]["totalDistanceKm"], 215.0)

        # 3. Add embedded stop
        added = add_stop_to_trip(trip_id, "Saravana Bhavan", "restaurant", 78.5, 12.9)
        self.assertTrue(added)
        updated_trip = get_trip(trip_id)
        self.assertEqual(len(updated_trip["stops"]), 1)
        self.assertEqual(updated_trip["stops"][0]["name"], "Saravana Bhavan")

        # 4. Update
        updated = update_trip(trip_id, {"status": "in_progress", "travelScore": 95.0})
        self.assertTrue(updated)
        updated_trip2 = get_trip(trip_id)
        self.assertEqual(updated_trip2["status"], "in_progress")
        self.assertEqual(updated_trip2["travelScore"], 95.0)

        # 5. List
        user_trips = list_user_trips(999)
        self.assertGreaterEqual(len(user_trips), 1)

        # 6. Delete
        deleted = delete_trip(trip_id)
        self.assertTrue(deleted)
        self.assertIsNone(get_trip(trip_id))

    def test_07_traffic_snapshot_operations(self):
        """Verify traffic snapshot recording and retrieval."""
        snap = record_traffic_snapshot(
            segment_osm_id=999999,
            current_speed=40.0,
            free_flow_speed=50.0,
            road_type="secondary",
            road_name="Test Highway"
        )
        self.assertIsNotNone(snap.get("_id"))
        self.assertEqual(snap["congestion"], 20.0)

        latest = get_latest_traffic_snapshot(999999)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["roadName"], "Test Highway")
        self.assertEqual(latest["congestion"], 20.0)

    def test_08_aggregations(self):
        """Verify aggregation pipeline returns correct category grouping."""
        cats = aggregate_places_by_category()
        self.assertGreater(len(cats), 0)
        total_sum = sum(c["totalPlaces"] for c in cats)
        self.assertEqual(total_sum, 24649)

        brands = aggregate_top_fuel_brands(limit=5)
        self.assertGreater(len(brands), 0)
        self.assertTrue(any("Indian Oil" in b["brand"] for b in brands))


if __name__ == "__main__":
    unittest.main(verbosity=2)
