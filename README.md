# TravelDB — Database-Driven Multi-Stop Route Planning System

A comprehensive multi-tier database application developed for **BACSE202 Database Systems**, consolidating **DA1 (Problem Identification & Database Design)**, **DA2 (Relational Database Development in MySQL)**, and **DA3 (Advanced Database Technologies with MongoDB Atlas)**.

---

## 1. Project Architecture Overview

TravelDB implements a dual-engine architecture:
- **Primary Relational Tier (MySQL 8.0, InnoDB):** System of record for 22 normalized BCNF tables + 1 application table (`SAVED_TRIP_PLAN`), 10 views, 5 triggers, 10 stored procedures, and 5 functions. Contains 139,964 road segments, 621 cities, 24,649 service locations, and 210 precomputed routes extracted from OpenStreetMap (Southern Zone).
- **Secondary Document Tier (MongoDB Atlas):** Document store deployed on the cloud for:
  - `service_places`: 24,649 GeoJSON Point locations (`[longitude, latitude]`) with a `2dsphere` spatial index and compound category/rating indexes.
  - `trips`: Denormalized journey plans with embedded intermediate stops and routing metrics.
  - `traffic_snapshots`: Time-series traffic observations for road congestion analytics.
- **Application Tier (Flask & Streamlit):**
  - Flask web app on `http://127.0.0.1:5000` providing route selection, OSRM road geometry, turn-by-turn navigation, TomTom traffic flow sampling, and saved trip plans.
  - Streamlit comparative analytics dashboard on `http://localhost:8501` visualizing SQL vs NoSQL performance, `explain("executionStats")` query execution plans, geospatial radius exploration, and aggregation analytics.
- **Rule-Based Routing & Scoring:** Strictly deterministic mathematical scoring weighting time, fuel cost, distance, and congestion. Contains **no AI or machine learning models**.

---

## 2. Directory Structure

```
TravelDB_Project_To_Share/
├── README.md                          # Complete setup and execution guide
├── .gitignore                         # Protects credentials (.env) and backups
├── database/
│   └── TravelDB_backup.sql            # Master MySQL database dump (23 tables, views, triggers, routines)
└── traveldb_demo/
    ├── app.py                         # Flask application server (Web UI)
    ├── dashboard.py                   # Streamlit SQL vs NoSQL Comparative Dashboard (DA3)
    ├── mongo_db.py                    # Secure MongoDB Atlas connection manager & health check
    ├── sync_mysql_to_mongo.py         # Synchronizes SERVICE_LOCATION to MongoDB service_places
    ├── mongo_crud.py                  # CRUD operations for trips, service_places, traffic_snapshots
    ├── mongo_indexes.py               # Creates 2dsphere and compound indexes on Atlas
    ├── mongo_aggregations.py          # MongoDB aggregation pipelines (Appendix C.4)
    ├── explain_analyzer.py            # MongoDB explain('executionStats') execution plan analyzer
    ├── benchmark_sql_vs_nosql.py      # Repeatable SQL vs NoSQL benchmark (median & p95 latency)
    ├── backup_recovery.py             # Backup export & scratch restore verification test
    ├── security_roles_test.py         # Role-Based Access Control (RBAC) verification
    ├── test_da3.py                    # Automated test suite (8 unit tests)
    ├── setup.sql                      # Application table setup for SAVED_TRIP_PLAN
    ├── performance.sql                # MySQL index creation and EXPLAIN queries
    ├── security.sql                   # MySQL RBAC roles (app_reader, app_writer, admin_role)
    ├── sql_demo.sql                   # Real-data demo queries (aggregates, joins, subqueries)
    ├── requirements.txt               # Python package dependencies
    ├── .env.example                   # Environment configuration template
    ├── static/                        # CSS stylesheets
    └── templates/                     # Jinja2 HTML templates
```

---

## 3. Installation & Setup Instructions

### Step 1: Install Dependencies
Open Anaconda Prompt, Windows Command Prompt, or PowerShell:

```bash
cd traveldb_demo
python -m pip install -r requirements.txt
```

*(Packages installed: `Flask`, `mysql-connector-python`, `python-dotenv`, `pymongo`, `streamlit`)*

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` in `traveldb_demo`:

```bash
copy .env.example .env
```

Edit `.env` with your credentials:
```ini
# MySQL Configuration (Local System of Record)
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=TravelDB
FLASK_SECRET_KEY=traveldb-secure-demo-secret-key-2026

# MongoDB Atlas Configuration (DA3 Cloud Tier)
MONGODB_URI=mongodb+srv://<username>:<password>@traveldb.blnlsov.mongodb.net/?retryWrites=true&w=majority
MONGODB_DATABASE=TravelDB_Documents

# Optional Live Traffic API Key (TomTom)
TOMTOM_API_KEY=
```
> **Security Note:** Never commit or share your `.env` file. It is excluded by `.gitignore`.

---

## 4. Running the DA3 Components

### 1. Test Database Connectivity
```bash
python mongo_db.py
```
*Outputs cluster connection status and current collection document counts.*

### 2. Synchronize MySQL Service Locations to MongoDB Atlas
```bash
python sync_mysql_to_mongo.py
```
*Extracts all 24,649 service locations (with specialized attributes from `hospital`, `petrol_pump`, `ev_station`, `hotel`, and `restaurant`) and bulk-upserts them into MongoDB Atlas with valid GeoJSON `Point` coordinates `[longitude, latitude]`.*

### 3. Create Indexes (2dsphere & Compound Indexes)
```bash
python mongo_indexes.py
```
*Creates `2dsphere` spatial index on `service_places.location`, compound `(category, rating desc)`, compound `(category, name)`, and indexes for `trips` and `traffic_snapshots`.*

### 4. Execute Automated Unit Test Suite
```bash
python test_da3.py
```
*Runs 8 automated tests validating connectivity, sync integrity, GeoJSON coordinate bounds, index presence, geospatial `$near` search, trip CRUD lifecycle, traffic snapshots, and aggregation pipelines.*

### 5. Run Query Execution Plan Analysis (`explain`)
```bash
python explain_analyzer.py
```
*Executes `explain("executionStats")` to populate Table 5.8 of the project report, comparing `COLLSCAN` vs `IXSCAN` and `2dsphere` spatial index efficiency.*

### 6. Run SQL vs NoSQL Repeatable Performance Benchmark
```bash
python benchmark_sql_vs_nosql.py
```
*Runs 20 iterations per workload across spatial search, trip retrieval, aggregations, and point lookups to compute exact median and p95 latency for Table 5.9.*

### 7. Run Backup & Recovery Verification
```bash
python backup_recovery.py
```
*Exports collections to JSON backup files, restores into a scratch database, verifies 100% document parity, and tears down the scratch schema cleanly.*

### 8. Run Security & Access Control Verification
```bash
python security_roles_test.py
```
*Verifies credential isolation, environment variable hygiene, and least-privilege role mappings matching Table 3.10 and Appendix C.2.*

---

## 5. Running the User Applications

### A. Launch the Streamlit Comparative Analytics Dashboard (DA3)
```bash
streamlit run dashboard.py
```
Open **`http://localhost:8501`** in your browser to view:
- Live database tier status and collection statistics.
- Interactive **Geospatial Map Explorer** executing real-time `2dsphere` queries around major cities (Vellore, Chennai, Bengaluru, etc.).
- Benchmark comparison charts (median and p95 latency).
- Execution plan analysis visualizer.
- Aggregation distribution charts (places by category, top petrol pump brands).

### B. Launch the Flask Web Application
```bash
python app.py
```
Open **`http://127.0.0.1:5000`** in your browser to view:
- Route comparison with OSRM driving geometry and turn-by-turn navigation.
- Nearby service search along the route corridor.
- Saved trip plans with Create, Read, Update, Delete (CRUD).
