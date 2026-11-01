USE TravelDB;

-- 1. Confirm the main imported datasets
SELECT COUNT(*) AS RoadSegments FROM ROAD_SEGMENT;
SELECT COUNT(*) AS NamedCities FROM CITY WHERE CityName IS NOT NULL AND TRIM(CityName) <> '';
SELECT COUNT(*) AS ServiceLocations FROM SERVICE_LOCATION;
SELECT COUNT(*) AS Routes FROM ROUTE;

-- 2. Real-data aggregate query
SELECT RoadType, COUNT(*) AS SegmentCount,
       ROUND(SUM(Distance_km), 2) AS TotalKm,
       ROUND(AVG(Distance_km), 3) AS AverageKm
FROM ROAD_SEGMENT
GROUP BY RoadType
ORDER BY SegmentCount DESC;

-- 3. Join query
SELECT C.CityName, S.StateName
FROM CITY C JOIN STATE S ON S.StateID = C.StateID
WHERE C.CityName IS NOT NULL
ORDER BY S.StateName, C.CityName
LIMIT 15;

-- 4. Nested query
SELECT SegmentID, RoadName, RoadType, Distance_km
FROM ROAD_SEGMENT
WHERE Distance_km > (SELECT AVG(Distance_km) FROM ROAD_SEGMENT)
ORDER BY Distance_km DESC
LIMIT 10;

-- 5. Route details for readable source and destination names
SELECT R.RouteID, SC.CityName AS SourceCity, DC.CityName AS DestinationCity,
       R.TotalDistance, R.EstimatedTime, R.SafetyScore
FROM ROUTE R
JOIN CITY SC ON SC.CityID = R.SourceCityID
JOIN CITY DC ON DC.CityID = R.DestinationCityID
ORDER BY R.RouteID
LIMIT 15;

-- 6. Nearby service data count by category
SELECT LocationType, COUNT(*) AS Total
FROM SERVICE_LOCATION
GROUP BY LocationType
ORDER BY Total DESC;

-- 7. Example CRUD with app-managed table (execute one at a time)
-- INSERT INTO SAVED_TRIP_PLAN (PlanName, SourceCityID, DestinationCityID, TravelMode, Notes)
-- VALUES ('Demo travel plan', 408, 416, 'Car', 'Created for CRUD demonstration');
-- SELECT * FROM SAVED_TRIP_PLAN;
-- UPDATE SAVED_TRIP_PLAN SET Notes = 'Updated during demonstration' WHERE PlanName = 'Demo travel plan';
-- DELETE FROM SAVED_TRIP_PLAN WHERE PlanName = 'Demo travel plan';
