# TravelDB — live demonstration app

A small Flask + MySQL web application for the **AI-Powered Intelligent Travel Decision Support System for India** academic prototype. It uses the existing `TravelDB` database and the data already imported into it.

## Features

- Dashboard with live row counts from `ROAD_SEGMENT`, `CITY`, `SERVICE_LOCATION`, `ROUTE`, and `TRAFFIC_RECORD`.
- Route finder reads the actual source/destination route record from `ROUTE` and estimates fuel cost as `distance / user mileage × user fuel price`.
- Nearby-service search finds imported hospitals, fuel stations, EV chargers, hotels, and restaurants within a user-selected radius of a city's stored coordinates.
- Saved Trip Plans implements **Create, Read, Update, Delete (CRUD)** against an application-owned table, `SAVED_TRIP_PLAN`; this avoids modifying the imported OSM dataset during the demonstration.
- SQL examples for real-data queries, indexing, and `EXPLAIN` are included.

## Important prototype limitations to state in the viva

- The route catalogue currently contains 210 precomputed directional city-pair records for the project's selected cities. It is not a full India-wide routing engine and does not generate alternate road paths.
- The route time is a stored estimate, not a live traffic ETA.
- Fuel cost is an estimate based on the mileage and fuel price entered by the user.
- Nearby services are searched from the downloaded OpenStreetMap extract. Search radius is measured straight-line from city coordinates; it is not driving distance.
- The current application does not implement login/authentication, live traffic, MongoDB, cloud deployment, or a trained AI model. Present those as future extensions only if they have not been implemented separately.
- SQL data is real OSM-derived data and OSRM-generated route estimates. Do not describe all traffic values or route safety as real/live; current traffic/safety may be absent.

## Install and run on Windows / Anaconda Prompt

The existing Conda environment is expected to be named `traveldb`. If your ZIP is extracted to `C:\TravelDB\traveldb_demo`, use these steps.

1. Make sure MySQL Server is running and that the database name is `TravelDB`.
2. In MySQL CLI, create the application table by running the setup file. From the MySQL prompt:

   ```sql
   SOURCE C:/TravelDB/traveldb_demo/setup.sql;
   ```

   Alternatively, from Anaconda Prompt / Command Prompt:

   ```bat
   mysql -u root -p TravelDB < C:\TravelDB\traveldb_demo\setup.sql
   ```

3. Copy `.env.example` to `.env` in the project folder. Edit `.env` and replace `CHANGE_THIS_TO_YOUR_MYSQL_PASSWORD` with your actual local MySQL password. Do not upload or share `.env`.
4. Open Anaconda Prompt:

   ```bat
   conda activate traveldb
   cd /d C:\TravelDB\traveldb_demo
   python -m pip install -r requirements.txt
   python app.py
   ```

5. Open `http://127.0.0.1:5000` in your browser. Keep the terminal running during the demonstration.

If your project folder is somewhere else, use that folder's path in the commands above.

## Live demo sequence (about 4–6 minutes)

1. Open the Dashboard and show the counts are read from MySQL.
2. Open Route Finder. Choose **Vellore → Chennai** (known project city IDs: 3 and 408) or **Chennai → Bengaluru** (IDs 408 and 416). Enter mileage and fuel price. Explain that cost is estimated, not a live quote.
3. Open Nearby Services. Choose a city, category (for example `hospital`), and radius. Show the distance-sorted results.
4. Open Saved Trip Plans. Create a plan, show it in the list, edit it, and delete it.
5. Switch to MySQL and run:

   ```sql
   SELECT * FROM SAVED_TRIP_PLAN;
   SELECT COUNT(*) FROM ROAD_SEGMENT;
   SELECT COUNT(*) FROM SERVICE_LOCATION;
   SELECT COUNT(*) FROM ROUTE;
   ```

   This demonstrates that the frontend operations affect the database while original imported data remains intact.

## SQL files included

- `setup.sql` — creates `SAVED_TRIP_PLAN` and foreign keys.
- `sql_demo.sql` — real-data row counts, aggregate query, join, nested query, route details, and commented CRUD examples.
- `performance.sql` — optional indexes and `EXPLAIN` statements. Run the `CREATE INDEX` statements only once; a repeated index name will cause an error.

## Database connection configuration

`.env` supports `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`, and `FLASK_SECRET_KEY`. For an offline local demo, `127.0.0.1`, port `3306`, and database `TravelDB` are the defaults.

This app is intended for a local academic demonstration only. It runs on `127.0.0.1`; do not expose the Flask debug server to a public network.
