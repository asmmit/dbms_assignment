USE TravelDB;

-- PERFORMANCE DEMONSTRATION
-- Step 1: Run the EXPLAIN queries below BEFORE creating the added indexes.
-- Record the type/key/rows columns from the result.
EXPLAIN SELECT RouteID, TotalDistance, EstimatedTime
FROM ROUTE
WHERE SourceCityID = 408 AND DestinationCityID = 416;

EXPLAIN SELECT ServiceLocationID, Name, Latitude, Longitude
FROM SERVICE_LOCATION
WHERE LocationType = 'hospital'
LIMIT 20;

-- Step 2: Create each index once. If an index already exists, skip that CREATE INDEX line.
CREATE INDEX idx_route_source_destination ON ROUTE (SourceCityID, DestinationCityID);
CREATE INDEX idx_service_type ON SERVICE_LOCATION (LocationType);
CREATE INDEX idx_road_type ON ROAD_SEGMENT (RoadType);
CREATE INDEX idx_city_state ON CITY (StateID);

-- Step 3: Run the same EXPLAIN queries again AFTER index creation and compare the plans.
EXPLAIN SELECT RouteID, TotalDistance, EstimatedTime
FROM ROUTE
WHERE SourceCityID = 408 AND DestinationCityID = 416;

EXPLAIN SELECT ServiceLocationID, Name, Latitude, Longitude
FROM SERVICE_LOCATION
WHERE LocationType = 'hospital'
LIMIT 20;

SHOW INDEX FROM ROUTE;
SHOW INDEX FROM SERVICE_LOCATION;
SHOW INDEX FROM ROAD_SEGMENT;
SHOW INDEX FROM CITY;
