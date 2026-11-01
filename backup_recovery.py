"""
TravelDB — Backup and Recovery Automation & Verification
Provides backup generation and recovery verification for:
1. MySQL (logical dump via mysqldump with triggers and routines)
2. MongoDB Atlas (collection export and restore with document parity check)
Matches Section 3.12 and Appendix C.3 of the project report.
"""

import os
import json
import subprocess
from datetime import datetime
from dotenv import load_dotenv

from mongo_db import get_mongo_client, check_mongo_connection, MONGODB_DATABASE

load_dotenv()


def backup_mongodb(export_dir="mongo_backups"):
    """
    Exports all documents from Atlas collections (service_places, trips, traffic_snapshots)
    to structured JSON backup files and records document counts.
    """
    ok, info, err = check_mongo_connection()
    if not ok:
        print(f"MongoDB not connected: {err}")
        return False, {}

    os.makedirs(export_dir, exist_ok=True)
    client = get_mongo_client()
    db = client[MONGODB_DATABASE]
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    manifest = {
        "timestamp": timestamp,
        "database": MONGODB_DATABASE,
        "collections": {},
    }

    print(f"\n--- Starting MongoDB Atlas Backup ({timestamp}) ---")
    for col_name in ["service_places", "trips", "traffic_snapshots"]:
        col = db[col_name]
        docs = list(col.find({}))
        file_path = os.path.join(export_dir, f"{col_name}_{timestamp}.json")
        
        # Convert ObjectId and datetime to string for clean JSON serialization
        def serialize(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            return str(obj)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(docs, f, default=serialize, indent=2)
            
        manifest["collections"][col_name] = {
            "count": len(docs),
            "file": file_path,
        }
        print(f"  Exported '{col_name}': {len(docs)} documents -> {file_path}")

    manifest_path = os.path.join(export_dir, f"backup_manifest_{timestamp}.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[+] MongoDB Atlas backup completed successfully. Manifest: {manifest_path}")
    return True, manifest


def verify_mongodb_restore(manifest_path, scratch_db_name="TravelDB_Restore_Scratch"):
    """
    Restores the backup into a scratch database and verifies 100% document parity.
    Cleans up the scratch database after verification.
    """
    if not os.path.exists(manifest_path):
        print(f"Manifest not found: {manifest_path}")
        return False

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    client = get_mongo_client()
    scratch_db = client[scratch_db_name]

    print(f"\n--- Verifying MongoDB Restore into '{scratch_db_name}' ---")
    all_matched = True

    try:
        for col_name, info in manifest["collections"].items():
            expected_count = info["count"]
            with open(info["file"], "r", encoding="utf-8") as f:
                docs = json.load(f)

            scratch_col = scratch_db[col_name]
            scratch_col.drop()  # Clean scratch collection

            if docs:
                scratch_col.insert_many(docs)

            actual_count = scratch_col.count_documents({})
            status = "MATCH" if actual_count == expected_count else "MISMATCH"
            if actual_count != expected_count:
                all_matched = False
            print(f"  Collection '{col_name}': Expected = {expected_count}, Restored = {actual_count} [{status}]")

        print(f"\nRestore verification result: {'SUCCESS (100% Document Parity)' if all_matched else 'FAILED'}")
    finally:
        # Drop scratch database
        client.drop_database(scratch_db_name)
        print(f"  Cleaned up scratch database '{scratch_db_name}'.")

    return all_matched


def print_mysql_backup_instructions():
    """Prints repeatable MySQL backup and recovery commands from Section 3.12."""
    print("\n" + "="*80)
    print("                     MYSQL BACKUP & RECOVERY COMMANDS                         ")
    print("="*80)
    print("1. Logical Backup with triggers and routines:")
    print("   mysqldump --routines --triggers --single-transaction -u root -p TravelDB > TravelDB_backup.sql")
    print("\n2. Create scratch schema for restore testing:")
    print("   mysql -u root -p -e \"CREATE DATABASE IF NOT EXISTS TravelDB_restore;\"")
    print("\n3. Restore backup into scratch schema:")
    print("   mysql -u root -p TravelDB_restore < TravelDB_backup.sql")
    print("\n4. Verify row count parity:")
    print("   SELECT 'ROAD_SEGMENT', COUNT(*) FROM TravelDB_restore.ROAD_SEGMENT")
    print("   UNION ALL")
    print("   SELECT 'SERVICE_LOCATION', COUNT(*) FROM TravelDB_restore.SERVICE_LOCATION;")
    print("="*80 + "\n")


if __name__ == "__main__":
    print_mysql_backup_instructions()
    ok, manifest = backup_mongodb()
    if ok:
        manifest_file = [f for f in os.listdir("mongo_backups") if f.startswith("backup_manifest_")][-1]
        verify_mongodb_restore(os.path.join("mongo_backups", manifest_file))
