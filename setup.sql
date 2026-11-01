USE TravelDB;

-- Application-managed records for demonstrating frontend CRUD.
-- This table does not alter or delete the imported OpenStreetMap records.
CREATE TABLE IF NOT EXISTS SAVED_TRIP_PLAN (
    PlanID INT AUTO_INCREMENT PRIMARY KEY,
    PlanName VARCHAR(120) NOT NULL,
    SourceCityID INT NOT NULL,
    DestinationCityID INT NOT NULL,
    TravelMode VARCHAR(30) NOT NULL DEFAULT 'Car',
    Notes VARCHAR(500) NULL,
    CreatedAt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_saved_trip_source
        FOREIGN KEY (SourceCityID) REFERENCES CITY(CityID),
    CONSTRAINT fk_saved_trip_destination
        FOREIGN KEY (DestinationCityID) REFERENCES CITY(CityID)
) ENGINE=InnoDB;
