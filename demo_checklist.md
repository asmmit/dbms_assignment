# Final demonstration checklist

## Before evaluation
- [ ] MySQL Server is running and `USE TravelDB;` works.
- [ ] `.env` exists and contains the correct local MySQL password.
- [ ] `SAVED_TRIP_PLAN` exists (`SHOW TABLES LIKE 'SAVED_TRIP_PLAN';`).
- [ ] `conda activate traveldb` succeeds.
- [ ] `python app.py` starts with no errors.
- [ ] Browser opens `http://127.0.0.1:5000`.
- [ ] Route search works for a supported city pair, e.g. Chennai (408) → Bengaluru (416).
- [ ] Nearby-service search returns results for a suitable city/category/radius.
- [ ] Create, update and delete a saved trip plan; verify with `SELECT * FROM SAVED_TRIP_PLAN;`.
- [ ] `sql_demo.sql` runs.
- [ ] If running `performance.sql`, create each index only once.
- [ ] Back up the database before the evaluation.

## Honest feature status
- Implemented in this package: Flask ↔ MySQL connectivity, live dashboard counts, stored route lookup, estimated fuel cost, proximity search on imported services, CRUD for saved trip plans, SQL demo queries, optional indexes/EXPLAIN.
- Not included in this package: real user login, live traffic ingestion, alternate-route generation, AI or machine-learning functionality, MongoDB, cloud database, public deployment, map visualization.

## Backup
Run from Windows Command Prompt / Anaconda Prompt (adjust path and credentials as needed):

```bat
mysqldump -u root -p TravelDB > C:\TravelDB\TravelDB_backup.sql
```

To restore to the same database after backing up an existing copy (this overwrites data in tables that are recreated by the dump), use:

```bat
mysql -u root -p TravelDB < C:\TravelDB\TravelDB_backup.sql
```

Do not test restore over the only copy of your live data before the demonstration.
