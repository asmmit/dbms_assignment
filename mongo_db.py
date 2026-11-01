"""
TravelDB — MongoDB Atlas Connection Manager
Provides connection handling, database client caching, and connectivity verification
for the DA3 document layer.
"""

import os
from urllib.parse import urlparse
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ConfigurationError

# Load environment variables
load_dotenv(override=True)

MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "TravelDB_Documents").strip()

_mongo_client = None


def get_mongo_client(timeout_ms=5000):
    """
    Returns a singleton MongoClient instance with connection timeout and pooling.
    Raises ValueError if MONGODB_URI is not set.
    """
    global _mongo_client
    if _mongo_client is None:
        if not MONGODB_URI:
            raise ValueError(
                "MONGODB_URI is not configured. Set MONGODB_URI in your .env file."
            )
        _mongo_client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=timeout_ms,
            connectTimeoutMS=timeout_ms,
            socketTimeoutMS=10000,
            maxPoolSize=50,
            retryWrites=True,
            appName="TravelDB_DA3",
        )
    return _mongo_client


def get_mongo_db():
    """Returns the configured MongoDB database instance."""
    client = get_mongo_client()
    return client[MONGODB_DATABASE]


def check_mongo_connection():
    """
    Checks MongoDB connectivity and returns (is_connected: bool, info: dict, error_msg: str).
    Ensures zero credential leakage in returned info or errors.
    """
    if not MONGODB_URI:
        return False, {}, "MONGODB_URI is not configured in .env."

    try:
        client = get_mongo_client(timeout_ms=4000)
        # Execute admin ping to verify connection
        client.admin.command("ping")
        db = client[MONGODB_DATABASE]
        collections = db.list_collection_names()
        
        # Sanitize URI for display: mask user/password
        parsed = urlparse(MONGODB_URI)
        sanitized_host = parsed.hostname or "MongoDB Atlas Cluster"
        
        info = {
            "connected": True,
            "cluster_host": sanitized_host,
            "database": MONGODB_DATABASE,
            "collections": collections,
            "counts": {
                c: db[c].count_documents({}) for c in collections
            },
        }
        return True, info, None
    except (ConnectionFailure, ConfigurationError, Exception) as exc:
        return False, {}, f"MongoDB connection failed: {exc.__class__.__name__} - {str(exc)}"


def close_mongo_client():
    """Closes the cached MongoClient instance."""
    global _mongo_client
    if _mongo_client is not None:
        _mongo_client.close()
        _mongo_client = None


if __name__ == "__main__":
    ok, details, err = check_mongo_connection()
    if ok:
        print(f"MongoDB Atlas Connected Successfully to '{details['database']}' on '{details['cluster_host']}'")
        print("Collections & document counts:", details["counts"])
    else:
        print("Connection Failed:", err)
