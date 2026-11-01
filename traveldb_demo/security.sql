USE TravelDB;

-- Optional MySQL 8.0+ role/user demo. Change the password before use.
-- Run this with an administrator account. Skip if roles are unsupported on your MySQL version.
CREATE ROLE IF NOT EXISTS 'traveldb_app_role';

GRANT SELECT ON TravelDB.STATE TO 'traveldb_app_role';
GRANT SELECT ON TravelDB.CITY TO 'traveldb_app_role';
GRANT SELECT ON TravelDB.ROAD_SEGMENT TO 'traveldb_app_role';
GRANT SELECT ON TravelDB.SERVICE_LOCATION TO 'traveldb_app_role';
GRANT SELECT ON TravelDB.ROUTE TO 'traveldb_app_role';
GRANT SELECT ON TravelDB.TRAFFIC_RECORD TO 'traveldb_app_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON TravelDB.SAVED_TRIP_PLAN TO 'traveldb_app_role';

CREATE USER IF NOT EXISTS 'traveldb_app'@'localhost' IDENTIFIED BY 'ChangeThisPassword!';
GRANT 'traveldb_app_role' TO 'traveldb_app'@'localhost';
SET DEFAULT ROLE 'traveldb_app_role' TO 'traveldb_app'@'localhost';

-- Verify permissions. You may need FLUSH PRIVILEGES after manual grant-table edits;
-- standard GRANT statements take effect immediately.
SHOW GRANTS FOR 'traveldb_app'@'localhost';

-- To use this limited account in the app, update .env:
-- MYSQL_USER=traveldb_app
-- MYSQL_PASSWORD=ChangeThisPassword!
