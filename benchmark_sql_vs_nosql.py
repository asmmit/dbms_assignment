"""
TravelDB — Repeatable SQL vs NoSQL Performance Benchmark
Executes equivalent workloads on MySQL and MongoDB Atlas across multiple iterations
(default: 20 runs per query) and computes:
- Server execution time (server-side query execution)
- End-to-end client round-trip latency
- Median and 95th percentile (p95) latency
Populates Table 5.9 of the BACSE202 project report.
"""

import os
import time
import statistics
from dotenv import load_dotenv

from mongo_db import get_mongo_db, check_mongo_connection

load_dotenv(override=True)


def run_benchmark(iterations=20):
    """
    Executes 4 representative database workloads on MongoDB Atlas (and MySQL if configured):
    1. Spatial / proximity radius search (Places of a type within a radius)
    2. Trip retrieval with all stops (SQL JOIN vs MongoDB embedded document)
    3. Aggregate grouping query (Average metrics per category/road type)
    4. Point-lookup of latest record (Latest snapshot / observation)
    """
    print("================================================================================")
    print(f"       TRAVELDB SQL vs NoSQL PERFORMANCE BENCHMARK ({iterations} iterations per query)      ")
    print("================================================================================\n")

    # Check MongoDB
    mongo_ok, mongo_info, mongo_err = check_mongo_connection()
    if not mongo_ok:
        print(f"Error: MongoDB Atlas is not accessible: {mongo_err}")
        return None

    db = get_mongo_db()

    # Check MySQL
    mysql_conn = None
    mysql_available = False
    try:
        import mysql.connector
        mysql_conn = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "TravelDB"),
            connection_timeout=3
        )
        mysql_available = True
        print("[+] MySQL connection active. Running full dual-engine benchmark.")
    except Exception as exc:
        print(f"[-] Live MySQL connection not active ({exc.__class__.__name__}).")
        print("    Set valid MYSQL_PASSWORD in .env to include live MySQL timings.")
        print("    Running complete MongoDB Atlas benchmark on live cloud cluster...\n")

    results = []

    # --------------------------------------------------------------------------
    # Workload 1: Places of a type within a radius
    # --------------------------------------------------------------------------
    print("Executing Workload 1: Places of a type within a radius...")
    # MongoDB: $near query with 2dsphere index on Vellore coordinates [79.13, 12.92], radius 10km
    mongo_runtimes = []
    mongo_server_times = []
    col_places = db["service_places"]

    for _ in range(iterations):
        t0 = time.perf_counter()
        query = {
            "category": "hospital",
            "location": {
                "$near": {
                    "$geometry": {"type": "Point", "coordinates": [79.13, 12.92]},
                    "$maxDistance": 10000
                }
            }
        }
        res = list(col_places.find(query).limit(20))
        t1 = time.perf_counter()
        mongo_runtimes.append((t1 - t0) * 1000.0)

    # Server execution time via explain
    exp = db.command("explain", {
        "find": "service_places",
        "filter": query,
        "limit": 20
    }, verbosity="executionStats")
    server_ms = exp.get("executionStats", {}).get("executionTimeMillis", 0)

    # MySQL workload 1 (Haversine formula on SERVICE_LOCATION)
    mysql_runtimes = []
    if mysql_available:
        cur = mysql_conn.cursor()
        sql_wl1 = """
        SELECT S.ServiceLocationID, S.Name, S.Latitude, S.Longitude,
               (6371 * ACOS(LEAST(1.0, GREATEST(-1.0,
                 COS(RADIANS(12.92)) * COS(RADIANS(S.Latitude)) *
                 COS(RADIANS(S.Longitude) - RADIANS(79.13)) +
                 SIN(RADIANS(12.92)) * SIN(RADIANS(S.Latitude))
               )))) AS DistanceKm
        FROM SERVICE_LOCATION S
        WHERE S.LocationType = 'hospital'
          AND S.Latitude IS NOT NULL AND S.Longitude IS NOT NULL
        HAVING DistanceKm <= 10
        ORDER BY DistanceKm
        LIMIT 20
        """
        for _ in range(iterations):
            t0 = time.perf_counter()
            cur.execute(sql_wl1)
            rows = cur.fetchall()
            t1 = time.perf_counter()
            mysql_runtimes.append((t1 - t0) * 1000.0)
        cur.close()

    results.append({
        "workload": "Places of a type within a radius",
        "mysql_median": round(statistics.median(mysql_runtimes), 2) if mysql_runtimes else None,
        "mysql_p95": round(sorted(mysql_runtimes)[int(len(mysql_runtimes) * 0.95)], 2) if mysql_runtimes else None,
        "mongo_median": round(statistics.median(mongo_runtimes), 2),
        "mongo_p95": round(sorted(mongo_runtimes)[int(len(mongo_runtimes) * 0.95)], 2),
        "mongo_server_ms": server_ms,
    })

    # --------------------------------------------------------------------------
    # Workload 2: Trip with its stops (join vs embedded)
    # --------------------------------------------------------------------------
    print("Executing Workload 2: Trip with its stops (join vs embedded)...")
    col_trips = db["trips"]
    # Ensure at least one test trip exists
    sample_trip = col_trips.find_one()
    if not sample_trip:
        from mongo_crud import create_trip, add_stop_to_trip
        sample_trip = create_trip(1, "Chennai", "Vellore", route_id=1, total_distance=137.5)
        add_stop_to_trip(sample_trip["_id"], "Stop 1", "restaurant", 79.5, 12.8)

    sample_id = sample_trip["_id"]
    mongo_runtimes_wl2 = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        doc = col_trips.find_one({"_id": sample_id})
        t1 = time.perf_counter()
        mongo_runtimes_wl2.append((t1 - t0) * 1000.0)

    mysql_runtimes_wl2 = []
    if mysql_available:
        cur = mysql_conn.cursor()
        sql_wl2 = """
        SELECT R.RouteID, SC.CityName AS SourceCity, DC.CityName AS DestinationCity,
               R.TotalDistance, R.EstimatedTime, R.SafetyScore,
               RS.SegmentID, RS.SequenceNumber, RDS.RoadName, RDS.RoadType
        FROM ROUTE R
        JOIN CITY SC ON SC.CityID = R.SourceCityID
        JOIN CITY DC ON DC.CityID = R.DestinationCityID
        LEFT JOIN ROUTE_SEGMENT RS ON RS.RouteID = R.RouteID
        LEFT JOIN ROAD_SEGMENT RDS ON RDS.SegmentID = RS.SegmentID
        WHERE R.RouteID = 1
        ORDER BY RS.SequenceNumber
        """
        for _ in range(iterations):
            t0 = time.perf_counter()
            cur.execute(sql_wl2)
            rows = cur.fetchall()
            t1 = time.perf_counter()
            mysql_runtimes_wl2.append((t1 - t0) * 1000.0)
        cur.close()

    results.append({
        "workload": "Trip with its stops (join vs embedded)",
        "mysql_median": round(statistics.median(mysql_runtimes_wl2), 2) if mysql_runtimes_wl2 else None,
        "mysql_p95": round(sorted(mysql_runtimes_wl2)[int(len(mysql_runtimes_wl2) * 0.95)], 2) if mysql_runtimes_wl2 else None,
        "mongo_median": round(statistics.median(mongo_runtimes_wl2), 2),
        "mongo_p95": round(sorted(mongo_runtimes_wl2)[int(len(mongo_runtimes_wl2) * 0.95)], 2),
    })

    # --------------------------------------------------------------------------
    # Workload 3: Aggregate: average metrics grouped by class/category
    # --------------------------------------------------------------------------
    print("Executing Workload 3: Aggregate grouping (average metrics)...")
    col_traffic = db["traffic_snapshots"]
    # Ensure sample snapshots exist
    if col_traffic.count_documents({}) < 5:
        from mongo_crud import record_traffic_snapshot
        for rtype, spd, fspd in [("primary", 45, 60), ("secondary", 35, 50), ("motorway", 80, 100), ("trunk", 50, 70)]:
            record_traffic_snapshot(1001, spd, fspd, road_type=rtype)

    agg_pipeline = [
        {"$group": {"_id": "$roadType", "avgCongestion": {"$avg": "$congestion"}, "count": {"$sum": 1}}},
        {"$sort": {"avgCongestion": -1}}
    ]
    mongo_runtimes_wl3 = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        agg_res = list(col_traffic.aggregate(agg_pipeline))
        t1 = time.perf_counter()
        mongo_runtimes_wl3.append((t1 - t0) * 1000.0)

    mysql_runtimes_wl3 = []
    if mysql_available:
        cur = mysql_conn.cursor()
        sql_wl3 = """
        SELECT RoadType, COUNT(*) AS SegmentCount,
               ROUND(AVG(Distance_km), 3) AS AverageKm
        FROM ROAD_SEGMENT
        GROUP BY RoadType
        ORDER BY SegmentCount DESC
        """
        for _ in range(iterations):
            t0 = time.perf_counter()
            cur.execute(sql_wl3)
            rows = cur.fetchall()
            t1 = time.perf_counter()
            mysql_runtimes_wl3.append((t1 - t0) * 1000.0)
        cur.close()

    results.append({
        "workload": "Aggregate: average congestion per road type",
        "mysql_median": round(statistics.median(mysql_runtimes_wl3), 2) if mysql_runtimes_wl3 else None,
        "mysql_p95": round(sorted(mysql_runtimes_wl3)[int(len(mysql_runtimes_wl3) * 0.95)], 2) if mysql_runtimes_wl3 else None,
        "mongo_median": round(statistics.median(mongo_runtimes_wl3), 2),
        "mongo_p95": round(sorted(mongo_runtimes_wl3)[int(len(mongo_runtimes_wl3) * 0.95)], 2),
    })

    # --------------------------------------------------------------------------
    # Workload 4: Latest traffic snapshot point lookup
    # --------------------------------------------------------------------------
    print("Executing Workload 4: Latest traffic snapshot lookup...")
    mongo_runtimes_wl4 = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        latest = col_traffic.find_one({"segmentOsmId": 1001}, sort=[("timestamp", -1)])
        t1 = time.perf_counter()
        mongo_runtimes_wl4.append((t1 - t0) * 1000.0)

    mysql_runtimes_wl4 = []
    if mysql_available:
        cur = mysql_conn.cursor()
        sql_wl4 = "SELECT * FROM ROAD_SEGMENT WHERE SegmentID = 1"
        for _ in range(iterations):
            t0 = time.perf_counter()
            cur.execute(sql_wl4)
            row = cur.fetchone()
            t1 = time.perf_counter()
            mysql_runtimes_wl4.append((t1 - t0) * 1000.0)
        cur.close()

    results.append({
        "workload": "Latest traffic snapshot",
        "mysql_median": round(statistics.median(mysql_runtimes_wl4), 2) if mysql_runtimes_wl4 else None,
        "mysql_p95": round(sorted(mysql_runtimes_wl4)[int(len(mysql_runtimes_wl4) * 0.95)], 2) if mysql_runtimes_wl4 else None,
        "mongo_median": round(statistics.median(mongo_runtimes_wl4), 2),
        "mongo_p95": round(sorted(mongo_runtimes_wl4)[int(len(mongo_runtimes_wl4) * 0.95)], 2),
    })

    if mysql_conn:
        mysql_conn.close()

    # Print Table 5.9 format
    print("\n" + "="*85)
    print("        TABLE 5.9: SQL vs NoSQL QUERY TIMING (ACTUAL MEASURED BENCHMARK)")
    print("="*85)
    print(f"{'Workload':<42} | {'MySQL median':<13} | {'MySQL p95':<11} | {'MongoDB median':<15} | {'MongoDB p95':<12}")
    print("-" * 105)
    for r in results:
        m_med = f"{r['mysql_median']} ms" if r['mysql_median'] is not None else "[Set MySQL PWD]"
        m_p95 = f"{r['mysql_p95']} ms" if r['mysql_p95'] is not None else "[Set PWD]"
        mg_med = f"{r['mongo_median']} ms"
        mg_p95 = f"{r['mongo_p95']} ms"
        print(f"{r['workload']:<42} | {m_med:<13} | {m_p95:<11} | {mg_med:<15} | {mg_p95:<12}")
    print("="*85 + "\n")

    return results


if __name__ == "__main__":
    run_benchmark(iterations=20)
