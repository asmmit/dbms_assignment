"""
TravelDB — MySQL to MongoDB Atlas Synchronization
Synchronizes the SERVICE_LOCATION table and its 5 specialized subtype tables
(hospital, petrol_pump, ev_station, hotel, restaurant) into the MongoDB Atlas
'service_places' collection with standard GeoJSON Point geometry: [longitude, latitude].

Data Source:
1. Live MySQL instance (if available and accessible).
2. Fallback to parsing TravelDB_backup.sql (preserving 100% actual OSM data).
"""

import os
import re
import sys
from datetime import datetime
from dotenv import load_dotenv
import pymongo
from pymongo import ReplaceOne

from mongo_db import get_mongo_db, check_mongo_connection

load_dotenv(override=True)


def parse_sql_values(values_str):
    """
    Robust SQL values tuple parser that handles quoted strings, escaped characters,
    commas inside quotes, and NULLs without external SQL parsing engines.
    """
    tuples = []
    i = 0
    n = len(values_str)
    
    while i < n:
        # Find start of tuple
        while i < n and values_str[i] != '(':
            i += 1
        if i >= n:
            break
        i += 1  # Skip '('
        
        elements = []
        curr = []
        in_quote = False
        quote_char = None
        
        while i < n:
            c = values_str[i]
            if in_quote:
                if c == '\\' and i + 1 < n:
                    curr.append(values_str[i + 1])
                    i += 2
                    continue
                elif c == quote_char:
                    # Check for doubled quote escape
                    if i + 1 < n and values_str[i + 1] == quote_char:
                        curr.append(quote_char)
                        i += 2
                        continue
                    else:
                        in_quote = False
                        quote_char = None
                else:
                    curr.append(c)
            else:
                if c in ("'", '"'):
                    in_quote = True
                    quote_char = c
                elif c == ',':
                    val = "".join(curr).strip()
                    elements.append(val)
                    curr = []
                elif c == ')':
                    val = "".join(curr).strip()
                    elements.append(val)
                    tuples.append(elements)
                    i += 1
                    break
                else:
                    curr.append(c)
            i += 1
            
    # Convert element values
    cleaned_tuples = []
    for t in tuples:
        cleaned = []
        for val in t:
            if val == "NULL":
                cleaned.append(None)
            elif val.startswith("'") and val.endswith("'"):
                cleaned.append(val[1:-1])
            elif val.startswith('"') and val.endswith('"'):
                cleaned.append(val[1:-1])
            else:
                # Try int or float
                try:
                    if "." in val:
                        cleaned.append(float(val))
                    else:
                        cleaned.append(int(val))
                except ValueError:
                    cleaned.append(val)
        cleaned_tuples.append(cleaned)
    return cleaned_tuples


def load_from_mysql():
    """Attempt to load service location data directly from MySQL."""
    import mysql.connector
    
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "TravelDB")
    
    conn = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connection_timeout=4,
    )
    cursor = conn.cursor(dictionary=True)
    
    query = """
    SELECT 
        s.ServiceLocationID, s.OSM_ID, s.Name, s.Latitude, s.Longitude, s.LocationType,
        s.Address, s.Operator, s.Brand, s.Postcode,
        h.EmergencyAvailable,
        p.Brand AS PumpBrand,
        ev.Operator AS EVOperator, ev.AvailablePorts,
        ht.Rating AS HotelRating,
        r.CuisineType, r.Rating AS RestaurantRating
    FROM service_location s
    LEFT JOIN hospital h ON s.ServiceLocationID = h.ServiceLocationID
    LEFT JOIN petrol_pump p ON s.ServiceLocationID = p.ServiceLocationID
    LEFT JOIN ev_station ev ON s.ServiceLocationID = ev.ServiceLocationID
    LEFT JOIN hotel ht ON s.ServiceLocationID = ht.ServiceLocationID
    LEFT JOIN restaurant r ON s.ServiceLocationID = r.ServiceLocationID
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    documents = []
    now = datetime.utcnow()
    for row in rows:
        lat = float(row["Latitude"]) if row["Latitude"] is not None else None
        lon = float(row["Longitude"]) if row["Longitude"] is not None else None
        
        doc = {
            "serviceLocationId": row["ServiceLocationID"],
            "osmId": row["OSM_ID"],
            "name": row["Name"] or "Unnamed Place",
            "category": row["LocationType"],
            "address": row["Address"] or "",
            "operator": row["Operator"] or row["EVOperator"] or "",
            "brand": row["Brand"] or row["PumpBrand"] or "",
            "postcode": row["Postcode"] or "",
            "rating": float(row["HotelRating"] or row["RestaurantRating"]) if (row["HotelRating"] or row["RestaurantRating"]) is not None else None,
            "emergencyAvailable": row["EmergencyAvailable"],
            "availablePorts": int(row["AvailablePorts"]) if row["AvailablePorts"] is not None else None,
            "cuisineType": row["CuisineType"],
            "syncedAt": now,
        }
        if lon is not None and lat is not None:
            doc["location"] = {
                "type": "Point",
                "coordinates": [lon, lat],
            }
        else:
            doc["location"] = None
            
        documents.append(doc)
    return documents


def load_from_sql_backup(backup_path):
    """Fallback: Parse service locations and subtypes directly from SQL dump."""
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found at {backup_path}")
        
    print(f"Reading service location data from SQL backup: {backup_path}...")
    
    hospitals = {}      # id -> EmergencyAvailable
    petrol_pumps = {}   # id -> Brand
    ev_stations = {}    # id -> (Operator, AvailablePorts)
    hotels = {}         # id -> Rating
    restaurants = {}    # id -> (CuisineType, Rating)
    
    # First pass: read subtypes
    with open(backup_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("INSERT INTO `hospital`") or line.startswith("INSERT INTO hospital"):
                tuples = parse_sql_values(line)
                for t in tuples:
                    if len(t) >= 2:
                        hospitals[t[0]] = t[1]
            elif line.startswith("INSERT INTO `petrol_pump`") or line.startswith("INSERT INTO petrol_pump"):
                tuples = parse_sql_values(line)
                for t in tuples:
                    if len(t) >= 2:
                        petrol_pumps[t[0]] = t[1]
            elif line.startswith("INSERT INTO `ev_station`") or line.startswith("INSERT INTO ev_station"):
                tuples = parse_sql_values(line)
                for t in tuples:
                    if len(t) >= 3:
                        ev_stations[t[0]] = (t[1], t[2])
            elif line.startswith("INSERT INTO `hotel`") or line.startswith("INSERT INTO hotel"):
                tuples = parse_sql_values(line)
                for t in tuples:
                    if len(t) >= 2:
                        hotels[t[0]] = float(t[1]) if t[1] is not None else None
            elif line.startswith("INSERT INTO `restaurant`") or line.startswith("INSERT INTO restaurant"):
                tuples = parse_sql_values(line)
                for t in tuples:
                    if len(t) >= 3:
                        restaurants[t[0]] = (t[1], float(t[2]) if t[2] is not None else None)

    print(f"Parsed subtypes: {len(hospitals)} hospitals, {len(petrol_pumps)} fuel pumps, "
          f"{len(ev_stations)} EV stations, {len(hotels)} hotels, {len(restaurants)} restaurants.")

    # Second pass: read service_location
    documents = []
    now = datetime.utcnow()
    
    with open(backup_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("INSERT INTO `service_location`") or line.startswith("INSERT INTO service_location"):
                tuples = parse_sql_values(line)
                for t in tuples:
                    if len(t) < 10:
                        continue
                    sec_id, osm_id, name, lat, lon, loc_type, addr, operator, brand, postcode = t[:10]
                    
                    # Subtype enrichment
                    emergency = hospitals.get(sec_id)
                    pump_brand = petrol_pumps.get(sec_id)
                    ev_info = ev_stations.get(sec_id, (None, None))
                    hotel_rating = hotels.get(sec_id)
                    rest_info = restaurants.get(sec_id, (None, None))
                    
                    final_rating = hotel_rating if hotel_rating is not None else rest_info[1]
                    cuisine = rest_info[0]
                    ev_op = ev_info[0]
                    ports = ev_info[1]
                    
                    doc = {
                        "serviceLocationId": int(sec_id),
                        "osmId": int(osm_id),
                        "name": str(name) if name else "Unnamed Place",
                        "category": str(loc_type).lower(),
                        "address": str(addr) if addr else "",
                        "operator": str(operator or ev_op or ""),
                        "brand": str(brand or pump_brand or ""),
                        "postcode": str(postcode) if postcode else "",
                        "rating": final_rating,
                        "emergencyAvailable": emergency,
                        "availablePorts": int(ports) if ports is not None else None,
                        "cuisineType": cuisine,
                        "syncedAt": now,
                    }
                    if lon is not None and lat is not None:
                        doc["location"] = {
                            "type": "Point",
                            "coordinates": [float(lon), float(lat)],
                        }
                    else:
                        doc["location"] = None
                        
                    documents.append(doc)
                    
    return documents


def sync_service_places(batch_size=1000):
    """Synchronizes MySQL service location data into MongoDB Atlas service_places."""
    ok, info, err = check_mongo_connection()
    if not ok:
        print(f"Error: Unable to connect to MongoDB Atlas: {err}")
        return False, 0
        
    db = get_mongo_db()
    collection = db["service_places"]
    
    documents = None
    # 1. Try MySQL
    try:
        print("Attempting to fetch service locations from MySQL...")
        documents = load_from_mysql()
        print(f"Successfully retrieved {len(documents)} records from MySQL.")
    except Exception as exc:
        print(f"Live MySQL query unavailable ({exc.__class__.__name__}). Falling back to SQL backup...")
        
    # 2. Fallback to SQL Backup
    if not documents:
        # Search possible paths for TravelDB_backup.sql
        candidate_paths = [
            os.path.join(os.path.dirname(__file__), "..", "database", "TravelDB_backup.sql"),
            os.path.join(os.path.dirname(__file__), "database", "TravelDB_backup.sql"),
            r"C:\TravelDB\database\TravelDB_backup.sql",
            r"C:\Users\asmit\Downloads\TravelDB_non_AI_revised\TravelDB_Project_To_Share\database\TravelDB_backup.sql",
        ]
        backup_path = next((p for p in candidate_paths if os.path.exists(p)), None)
        if not backup_path:
            print("Error: Could not locate TravelDB_backup.sql file.")
            return False, 0
        documents = load_from_sql_backup(backup_path)
        print(f"Successfully loaded {len(documents)} service places from backup.")

    if not documents:
        print("No documents found to sync.")
        return False, 0

    print(f"Syncing {len(documents)} documents to MongoDB Atlas collection 'service_places' in batches of {batch_size}...")
    
    total_synced = 0
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        operations = [
            ReplaceOne(
                {"serviceLocationId": doc["serviceLocationId"]},
                doc,
                upsert=True
            )
            for doc in batch
        ]
        result = collection.bulk_write(operations, ordered=False)
        total_synced += len(batch)
        print(f"  Processed {total_synced}/{len(documents)} documents...")

    final_count = collection.count_documents({})
    print(f"\nSync complete! MongoDB Atlas 'service_places' now contains {final_count} documents.")
    return True, final_count


if __name__ == "__main__":
    success, count = sync_service_places()
    if not success:
        sys.exit(1)
