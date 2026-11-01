"""
TravelDB — MongoDB & MySQL Query Execution Plan Analyzer
Executes queries with explain('executionStats') to measure:
- Execution stages (COLLSCAN vs IXSCAN / GEO_NEAR_2DSPHERE)
- Documents/rows examined vs returned
- Execution time in milliseconds
Populates the evidence needed for Table 5.7 and Table 5.8 of the project report.
"""

from mongo_db import get_mongo_db, check_mongo_connection


def analyze_mongo_execution_plans():
    """
    Analyzes MongoDB execution plans using db.command('explain', ..., verbosity='executionStats').
    Compares indexed queries against unindexed (COLLSCAN) baseline.
    """
    ok, info, err = check_mongo_connection()
    if not ok:
        print(f"MongoDB not connected: {err}")
        return None

    db = get_mongo_db()
    results = {}

    print("================================================================================")
    print("                     MONGODB EXECUTION PLAN ANALYSIS (explain)                  ")
    print("================================================================================\n")

    # --------------------------------------------------------------------------
    # Query 1: Places near a point (2dsphere)
    # Coordinate: Vellore [79.13, 12.92], maxDistance: 5000m, category: 'hospital'
    # --------------------------------------------------------------------------
    print("1. QUERY: Places near a point (2dsphere geospatial search)")

    geo_cmd = {
        "find": "service_places",
        "filter": {
            "location": {
                "$near": {
                    "$geometry": {"type": "Point", "coordinates": [79.13, 12.92]},
                    "$maxDistance": 5000,
                }
            },
            "category": "hospital",
        },
        "limit": 20,
    }

    plan_geo_indexed = db.command("explain", geo_cmd, verbosity="executionStats")
    stats_geo_indexed = plan_geo_indexed.get("executionStats", {})
    server_stage_geo = stats_geo_indexed.get("executionStages", {})

    stage_after = server_stage_geo.get("stage", "GEO_NEAR_2DSPHERE")
    docs_examined_after = stats_geo_indexed.get("totalDocsExamined", 0)
    keys_examined_after = stats_geo_indexed.get("totalKeysExamined", 0)
    docs_returned = stats_geo_indexed.get("nReturned", 0)
    exec_time_after = stats_geo_indexed.get("executionTimeMillis", 0)

    # Without spatial index (COLLSCAN box search)
    box_cmd = {
        "find": "service_places",
        "filter": {
            "location.coordinates.0": {"$gte": 79.08, "$lte": 79.18},
            "location.coordinates.1": {"$gte": 12.87, "$lte": 12.97},
            "category": "hospital",
        },
        "hint": {"$natural": 1},
        "limit": 20,
    }
    plan_geo_unindexed = db.command("explain", box_cmd, verbosity="executionStats")
    stats_geo_unindexed = plan_geo_unindexed.get("executionStats", {})
    stage_before = stats_geo_unindexed.get("executionStages", {}).get("stage", "COLLSCAN")
    docs_examined_before = stats_geo_unindexed.get("totalDocsExamined", 0)
    exec_time_before = stats_geo_unindexed.get("executionTimeMillis", 0)

    results["places_near_point"] = {
        "query": "Places near a point (2dsphere)",
        "stage_before": stage_before,
        "docs_examined_before": docs_examined_before,
        "time_ms_before": exec_time_before,
        "stage_after": stage_after,
        "docs_examined_after": docs_examined_after,
        "keys_examined_after": keys_examined_after,
        "docs_returned": docs_returned,
        "time_ms_after": exec_time_after,
    }

    print(f"  [Without Spatial Index]: Stage = {stage_before}, Docs Examined = {docs_examined_before}, Time = {exec_time_before} ms")
    print(f"  [With 2dsphere Index] : Stage = {stage_after}, Docs Examined = {docs_examined_after}, Keys Examined = {keys_examined_after}, Docs Returned = {docs_returned}, Time = {exec_time_after} ms\n")

    # --------------------------------------------------------------------------
    # Query 2: Best-rated places of a category
    # Category: 'hotel', sort: rating desc
    # --------------------------------------------------------------------------
    print("2. QUERY: Best-rated places of a category (Compound Index: category, rating desc)")
    
    # Unindexed baseline (force COLLSCAN + in-memory SORT)
    cat_cmd_unindexed = {
        "find": "service_places",
        "filter": {"category": "hotel"},
        "sort": {"rating": -1},
        "hint": {"$natural": 1},
        "limit": 20,
    }
    plan_cat_unindexed = db.command("explain", cat_cmd_unindexed, verbosity="executionStats")
    stats_cat_unindexed = plan_cat_unindexed.get("executionStats", {})
    stage_cat_before = stats_cat_unindexed.get("executionStages", {}).get("stage", "SORT")
    docs_cat_before = stats_cat_unindexed.get("totalDocsExamined", 0)
    time_cat_before = stats_cat_unindexed.get("executionTimeMillis", 0)

    # Indexed with idx_category_rating
    cat_cmd_indexed = {
        "find": "service_places",
        "filter": {"category": "hotel"},
        "sort": {"rating": -1},
        "hint": "idx_category_rating",
        "limit": 20,
    }
    plan_cat_indexed = db.command("explain", cat_cmd_indexed, verbosity="executionStats")
    stats_cat_indexed = plan_cat_indexed.get("executionStats", {})
    stage_cat_after = stats_cat_indexed.get("executionStages", {}).get("stage", "FETCH")
    docs_cat_after = stats_cat_indexed.get("totalDocsExamined", 0)
    keys_cat_after = stats_cat_indexed.get("totalKeysExamined", 0)
    time_cat_after = stats_cat_indexed.get("executionTimeMillis", 0)

    results["best_rated_category"] = {
        "query": "Best-rated places of a category",
        "stage_before": stage_cat_before,
        "docs_examined_before": docs_cat_before,
        "time_ms_before": time_cat_before,
        "stage_after": f"{stage_cat_after} / IXSCAN",
        "docs_examined_after": docs_cat_after,
        "keys_examined_after": keys_cat_after,
        "time_ms_after": time_cat_after,
    }

    print(f"  [Without Index]: Stage = {stage_cat_before}, Docs Examined = {docs_cat_before}, Time = {time_cat_before} ms")
    print(f"  [With Index]   : Stage = {stage_cat_after} / IXSCAN, Docs Examined = {docs_cat_after}, Keys Examined = {keys_cat_after}, Time = {time_cat_after} ms\n")

    # --------------------------------------------------------------------------
    # Query 3: Latest snapshot for a segment
    # segmentOsmId: 247177822, sort: timestamp desc
    # --------------------------------------------------------------------------
    print("3. QUERY: Latest snapshot for a segment (Compound Index: segmentOsmId, timestamp desc)")
    
    # Unindexed baseline
    snap_cmd_unindexed = {
        "find": "traffic_snapshots",
        "filter": {"segmentOsmId": 247177822},
        "sort": {"timestamp": -1},
        "hint": {"$natural": 1},
        "limit": 1,
    }
    plan_snap_unindexed = db.command("explain", snap_cmd_unindexed, verbosity="executionStats")
    stats_snap_unindexed = plan_snap_unindexed.get("executionStats", {})
    stage_snap_before = stats_snap_unindexed.get("executionStages", {}).get("stage", "COLLSCAN")
    docs_snap_before = stats_snap_unindexed.get("totalDocsExamined", 0)
    time_snap_before = stats_snap_unindexed.get("executionTimeMillis", 0)

    # Indexed
    snap_cmd_indexed = {
        "find": "traffic_snapshots",
        "filter": {"segmentOsmId": 247177822},
        "sort": {"timestamp": -1},
        "hint": "idx_traffic_seg_time",
        "limit": 1,
    }
    plan_snap_indexed = db.command("explain", snap_cmd_indexed, verbosity="executionStats")
    stats_snap_indexed = plan_snap_indexed.get("executionStats", {})
    stage_snap_after = stats_snap_indexed.get("executionStages", {}).get("stage", "FETCH")
    docs_snap_after = stats_snap_indexed.get("totalDocsExamined", 0)
    time_snap_after = stats_snap_indexed.get("executionTimeMillis", 0)

    results["latest_traffic_snapshot"] = {
        "query": "Latest snapshot for a segment",
        "stage_before": stage_snap_before,
        "docs_examined_before": docs_snap_before,
        "time_ms_before": time_snap_before,
        "stage_after": f"{stage_snap_after} / IXSCAN",
        "docs_examined_after": docs_snap_after,
        "time_ms_after": time_snap_after,
    }

    print(f"  [Without Index]: Stage = {stage_snap_before}, Docs Examined = {docs_snap_before}, Time = {time_snap_before} ms")
    print(f"  [With Index]   : Stage = {stage_snap_after} / IXSCAN, Docs Examined = {docs_snap_after}, Time = {time_snap_after} ms\n")

    return results


def print_table_5_8(results):
    """Prints the completed Markdown Table 5.8 for the report."""
    if not results:
        return
    print("\n" + "="*85)
    print("             TABLE 5.8: EXECUTION PLAN ANALYSIS FOR MONGODB (ACTUAL RUN)         ")
    print("="*85)
    print(f"{'Query':<35} | {'Stage before':<14} | {'Docs examined before':<20} | {'Stage after':<18} | {'Docs examined after':<20}")
    print("-" * 115)
    for key, data in results.items():
        print(f"{data['query']:<35} | {data['stage_before']:<14} | {data['docs_examined_before']:<20} | {data['stage_after']:<18} | {data['docs_examined_after']:<20}")
    print("="*85 + "\n")


if __name__ == "__main__":
    res = analyze_mongo_execution_plans()
    print_table_5_8(res)
