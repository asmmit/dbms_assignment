"""
TravelDB — SQL vs NoSQL Comparative Analytics Dashboard (DA3)
Built with Streamlit for interactive project demonstration and faculty evaluation.
Displays:
1. Live Database Health & Metrics (MySQL & MongoDB Atlas)
2. Interactive Geospatial (2dsphere) Amenity Search & Map Visualization
3. Benchmark Performance Comparisons (Median & p95 Latency)
4. Query Execution Plan Visualizer (explain executionStats)
5. Aggregation Analytics & Data Distributions
"""

import os
import time
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from mongo_db import get_mongo_db, check_mongo_connection
from mongo_crud import find_places_near
from mongo_aggregations import (
    aggregate_places_by_category,
    aggregate_top_fuel_brands,
    aggregate_traffic_by_road_type,
)
from explain_analyzer import analyze_mongo_execution_plans
from benchmark_sql_vs_nosql import run_benchmark

load_dotenv()

st.set_page_config(
    page_title="TravelDB — SQL vs NoSQL Dashboard",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🗺️ TravelDB: Multi-Stop Route Planning System")
st.caption("BACSE202 Database Systems — Digital Assignment 3 (DA3) Advanced Database Technologies")

# Reload .env on each page rerun to detect credential updates dynamically
load_dotenv(override=True)

# -----------------------------------------------------------------------------
# SIDEBAR: Connectivity & Navigation
# -----------------------------------------------------------------------------
st.sidebar.header("🔌 System Connections")
mongo_ok, mongo_info, mongo_err = check_mongo_connection()

if mongo_ok:
    st.sidebar.success(f"MongoDB Atlas Connected\n\nDB: `{mongo_info['database']}`")
    st.sidebar.text(f"Host: {mongo_info['cluster_host']}")
else:
    st.sidebar.error(f"MongoDB Atlas Disconnected\n\n{mongo_err}")

# Check MySQL
mysql_ok = False
mysql_roads_count = None
try:
    import mysql.connector
    conn = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "TravelDB"),
        connection_timeout=2
    )
    cur = conn.cursor()
    cur.execute("SHOW TABLES LIKE 'road_segment'")
    has_road = cur.fetchone()
    if has_road:
        cur.execute("SELECT COUNT(*) FROM road_segment")
        mysql_roads_count = cur.fetchone()[0]
    conn.close()
    mysql_ok = True
    st.sidebar.success(f"MySQL 8.0 Connected (Local)\n\nUser: `{os.getenv('MYSQL_USER', 'root')}`")
except Exception as e:
    st.sidebar.warning(f"MySQL Local: Not connected ({e.__class__.__name__})")

# -----------------------------------------------------------------------------
# TABS
# -----------------------------------------------------------------------------
tabs = st.tabs([
    "📊 Overview & Record Counts",
    "📍 Spatial Search & Map (2dsphere)",
    "⚡ SQL vs NoSQL Benchmark",
    "🔍 Execution Plan Analysis (EXPLAIN)",
    "📈 Aggregation Analytics",
])

# =============================================================================
# TAB 1: Overview & Counts
# =============================================================================
with tabs[0]:
    st.subheader("Database Tier Status & Collection Volumes")
    col1, col2, col3, col4 = st.columns(4)

    if mongo_ok:
        counts = mongo_info.get("counts", {})
        col1.metric("Service Places (Atlas)", f"{counts.get('service_places', 0):,}")
        col2.metric("Trips (Document Store)", f"{counts.get('trips', 0):,}")
        col3.metric("Traffic Snapshots", f"{counts.get('traffic_snapshots', 0):,}")
    else:
        col1.metric("Service Places", "Offline")
        col2.metric("Trips", "Offline")
        col3.metric("Traffic Snapshots", "Offline")

    if mysql_roads_count is not None:
        col4.metric("Road Segments (MySQL Live)", f"{mysql_roads_count:,}")
    else:
        col4.metric("Road Segments (Master Data)", "139,964")

    st.markdown("---")
    st.markdown("""
    ### Architectural Roles in TravelDB
    - **MySQL (Primary Relational Store):** Holds normalized master data across 22 BCNF tables, including 139,964 road segments, 621 cities, 210 precomputed routes, and user profile entities. Enforces ACID constraints, relational foreign keys, views, stored procedures, and triggers.
    - **MongoDB Atlas (Secondary Document Store):** Holds denormalized `service_places` with valid GeoJSON `Point` coordinates, indexed with a `2dsphere` spatial index; full `trips` documents with embedded intermediate stop arrays; and append-heavy `traffic_snapshots` time-series observations.
    """)

# =============================================================================
# TAB 2: Spatial Search & Map
# =============================================================================
with tabs[1]:
    st.subheader("Interactive Proximity Search via MongoDB 2dsphere Index")
    st.write(
        "Demonstrates native geospatial `$near` queries on the `service_places` collection. "
        "Coordinates are evaluated on a spherical Earth model (WGS84)."
    )

    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)
    with col_ctrl1:
        city_coords = {
            "Vellore": (79.1325, 12.9165),
            "Chennai": (80.2707, 13.0827),
            "Bengaluru": (77.5946, 12.9716),
            "Coimbatore": (76.9558, 11.0168),
            "Madurai": (78.1198, 9.9252),
            "Salem": (78.1460, 11.6643),
        }
        selected_city = st.selectbox("Search Center Point", list(city_coords.keys()), index=0)
        c_lon, c_lat = city_coords[selected_city]

    with col_ctrl2:
        cat_options = ["hospital", "petrol_pump", "ev_station", "hotel", "restaurant"]
        selected_cat = st.selectbox("Amenity Category", cat_options, index=0)

    with col_ctrl3:
        search_radius_km = st.slider("Search Radius (km)", min_value=1, max_value=30, value=5)

    if st.button("🔍 Search Nearby Places in Atlas", type="primary"):
        if not mongo_ok:
            st.error("Cannot execute: MongoDB Atlas is disconnected.")
        else:
            t0 = time.perf_counter()
            places = find_places_near(c_lon, c_lat, max_distance_meters=search_radius_km * 1000, category=selected_cat, limit=50)
            elapsed = (time.perf_counter() - t0) * 1000.0

            st.success(f"Found {len(places)} {selected_cat}s within {search_radius_km} km of {selected_city} in **{elapsed:.2f} ms**!")

            if places:
                map_data = []
                table_rows = []
                for p in places:
                    coords = p.get("location", {}).get("coordinates", [None, None])
                    if coords[0] is not None and coords[1] is not None:
                        map_data.append({"lon": coords[0], "lat": coords[1], "name": p.get("name")})
                        table_rows.append({
                            "Name": p.get("name"),
                            "Category": p.get("category"),
                            "Brand / Operator": p.get("brand") or p.get("operator") or "—",
                            "Emergency": p.get("emergencyAvailable") or "—",
                            "Ports": p.get("availablePorts") or "—",
                            "Rating": p.get("rating") or "—",
                            "Longitude": coords[0],
                            "Latitude": coords[1],
                        })

                if map_data:
                    st.map(pd.DataFrame(map_data), zoom=12)

                st.dataframe(pd.DataFrame(table_rows), use_container_width=True)
            else:
                st.info(f"No {selected_cat} found within {search_radius_km} km. Try increasing the radius.")

# =============================================================================
# TAB 3: SQL vs NoSQL Benchmark
# =============================================================================
with tabs[2]:
    st.subheader("SQL vs NoSQL Performance Comparison (Table 5.9)")
    st.write(
        "Executes equivalent workloads across repeated iterations (default 20) and computes "
        "median and 95th percentile (p95) execution times on live databases."
    )

    if st.button("🚀 Run Live Benchmark (20 Iterations)"):
        with st.spinner("Benchmarking workloads on live cluster..."):
            bench_results = run_benchmark(iterations=20)
            if bench_results:
                st.session_state["benchmark_data"] = bench_results

    if "benchmark_data" in st.session_state:
        df_bench = pd.DataFrame(st.session_state["benchmark_data"])
        st.dataframe(df_bench, use_container_width=True)

        chart_df = df_bench[["workload", "mongo_median", "mongo_p95"]].set_index("workload")
        st.bar_chart(chart_df)
    else:
        st.info("Click the button above to run the live benchmark suite.")

# =============================================================================
# TAB 4: Execution Plan Analysis
# =============================================================================
with tabs[3]:
    st.subheader("Query Optimization & Execution Plan Analysis (Table 5.8)")
    st.write(
        "Compares server execution stages, documents examined, and keys examined "
        "using `explain('executionStats')` on indexed vs unindexed collection structures."
    )

    if st.button("🔬 Analyze Execution Plans"):
        with st.spinner("Analyzing query execution stages via MongoDB explain..."):
            plans = analyze_mongo_execution_plans()
            if plans:
                st.session_state["explain_data"] = plans

    if "explain_data" in st.session_state:
        p_data = st.session_state["explain_data"]
        rows = []
        for k, v in p_data.items():
            rows.append({
                "Query Description": v["query"],
                "Stage Before Index": v["stage_before"],
                "Docs Examined (Before)": v["docs_examined_before"],
                "Stage After Index": v["stage_after"],
                "Docs Examined (After)": v["docs_examined_after"],
                "Server Time (After)": f"{v['time_ms_after']} ms",
            })
        st.table(pd.DataFrame(rows))
        st.markdown("""
        **Key Takeaways:**
        - **2dsphere Spatial Index:** Eliminates scanning all 24,649 documents; evaluates only candidate spatial buckets (docs examined drops from 3,888+ to 75).
        - **Compound (Category, Rating desc) Index:** Completely avoids full collection scan (`COLLSCAN`) and memory sort (`SORT`); serves sorted results directly via index scan (`IXSCAN`), reducing docs examined from 24,649 to 20!
        """)

# =============================================================================
# TAB 5: Aggregation Analytics
# =============================================================================
with tabs[4]:
    st.subheader("MongoDB Aggregation Pipelines (Appendix C.4)")
    
    col_ag1, col_ag2 = st.columns(2)
    with col_ag1:
        st.markdown("#### Places by Category")
        cat_data = aggregate_places_by_category()
        if cat_data:
            df_cat = pd.DataFrame(cat_data).set_index("category")
            st.bar_chart(df_cat["totalPlaces"])
            st.dataframe(df_cat, use_container_width=True)

    with col_ag2:
        st.markdown("#### Top Fuel Pump Brands")
        brand_data = aggregate_top_fuel_brands(limit=10)
        if brand_data:
            df_brand = pd.DataFrame(brand_data).set_index("brand")
            st.bar_chart(df_brand["stationCount"])
            st.dataframe(df_brand, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Average Congestion by Road Type (Traffic Snapshots)")
    traffic_data = aggregate_traffic_by_road_type()
    if traffic_data:
        df_tr = pd.DataFrame(traffic_data).set_index("roadType")
        st.dataframe(df_tr, use_container_width=True)
    else:
        st.info("No traffic snapshots recorded yet. Record snapshots via Route search or CRUD.")
