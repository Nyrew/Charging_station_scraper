"""
Script to update merged_charging_stations collection after scraping.
Creates/updates merged stations by combining scraped data with user changes based on timestamps.
"""

import sys
import os
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import logging
from datetime import datetime
from config import Config

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_merged_charging_stations():
    """
    Update merged_charging_stations collection after scraping charging stations.
    Merges scraped data with user changes based on timestamps.
    """
    uri = Config.get_mongodb_uri()
    client = MongoClient(uri, server_api=ServerApi('1'))
    db = client[Config.get_mongodb_database()]
    
    scraped_collection = db["charging_stations"]
    merged_collection = db["merged_charging_stations"]
    id_map_collection = db["id_map"]
    user_changes_collection = db["user_changes"]
    
    logger.info("🔄 Starting update of merged_charging_stations after scraping...")
    
    # STEP 1: Clear existing merged collection
    logger.info("🗑️ Clearing existing merged_charging_stations collection...")
    delete_result = merged_collection.delete_many({})
    deleted_count = delete_result.deleted_count
    logger.info(f"✅ Deleted {deleted_count} existing merged documents")
    
    # STEP 2: Get all scraped stations and rebuild merged collection
    scraped_stations = list(scraped_collection.find({}))
    total = len(scraped_stations)
    logger.info(f"📊 Found {total} scraped charging stations to process")
    
    created_count = 0
    error_count = 0
    
    for scraped in scraped_stations:
        try:
            station_id = scraped.get("station_id")
            if not station_id:
                continue
            
            # Ensure station_id is int
            if isinstance(station_id, str):
                try:
                    station_id = int(station_id)
                except ValueError:
                    logger.warning(f"⚠️ Invalid station_id format: {station_id}")
                    continue
            
            # Get internal_id from id_map
            mapping = id_map_collection.find_one({
                "source": "scrape_charging",
                "source_id": station_id
            })
            
            if not mapping:
                logger.warning(f"⚠️ No mapping found for station_id: {station_id}")
                continue
            
            internal_id = mapping.get("internal_id")
            if not internal_id:
                logger.warning(f"⚠️ No internal_id in mapping for station_id: {station_id}")
                continue
            
            # Get all user changes for this station (ordered by timestamp)
            user_changes = list(user_changes_collection.find({
                "internal_id": internal_id,
                "target": "charger"
            }).sort("timestamp", 1))  # Ascending order (oldest first)
            
            # Build merged document by combining scraped data with user changes
            merged_doc = build_merged_charging_station_document(scraped, user_changes, station_id, internal_id)
            
            # Insert merged document (collection is already cleared, so always insert)
            merged_collection.insert_one(merged_doc)
            created_count += 1
                
        except Exception as e:
            logger.error(f"❌ Error processing station {scraped.get('station_id')}: {e}")
            error_count += 1
    
    logger.info("✅ Update completed:")
    logger.info(f"   Deleted (old): {deleted_count}")
    logger.info(f"   Total scraped: {total}")
    logger.info(f"   Created (new): {created_count}")
    logger.info(f"   Errors: {error_count}")
    
    # STEP 3: Create/ensure indexes exist
    logger.info("📇 Ensuring indexes exist...")
    try:
        existing_indexes = list(merged_collection.list_indexes())
        index_names = [idx["name"] for idx in existing_indexes]
        
        # Geospatial index for location (required for $geoNear)
        # Check if compound index exists (preferred over simple 2dsphere)
        compound_index_exists = "location_providers_compound" in index_names
        simple_index_exists = "location_2dsphere" in index_names
        
        if compound_index_exists:
            logger.info("✅ Compound index 'location_providers_compound' already exists (preferred)")
            # Drop simple index if it exists (compound index is sufficient)
            if simple_index_exists:
                try:
                    merged_collection.drop_index("location_2dsphere")
                    logger.info("✅ Dropped duplicate simple 'location_2dsphere' index (compound index is sufficient)")
                except Exception as e:
                    logger.warning(f"⚠️ Could not drop simple index: {e}")
        elif simple_index_exists:
            logger.info("✅ Simple 2dsphere index 'location_2dsphere' already exists")
        else:
            # Create compound index (better than simple index)
            try:
                merged_collection.create_index(
                    [("location", "2dsphere"), ("providers", 1)],
                    name="location_providers_compound",
                    background=True
                )
                logger.info("✅ Created compound index 'location_providers_compound' on merged_charging_stations")
            except Exception as e:
                logger.warning(f"⚠️ Could not create compound index: {e}")
                # Fallback to simple index
                merged_collection.create_index(
                    [("location", "2dsphere")],
                    name="location_2dsphere"
                )
                logger.info("✅ Created simple 2dsphere index 'location_2dsphere' as fallback")
        
        # Performance index for providers array field (provider filtering)
        if "providers_idx" not in index_names:
            merged_collection.create_index("providers", name="providers_idx")
            logger.info("✅ Created index 'providers_idx' on merged_charging_stations.providers")
        else:
            logger.info("✅ Index 'providers_idx' already exists")
    except Exception as e:
        logger.warning(f"⚠️ Could not create indexes: {e}")
        logger.info("💡 You can create indexes manually using MongoDB Compass or mongosh")
    
    client.close()


def build_merged_charging_station_document(scraped, user_changes, station_id, internal_id):
    """
    Build merged document by combining scraped data with user changes.
    For each field, uses the value with the most recent timestamp.
    """
    now = datetime.utcnow()
    
    # Extract address from location object
    location_obj = scraped.get("location")
    address = None
    if location_obj and isinstance(location_obj, dict):
        address = location_obj.get("address")
    
    # Get latitude/longitude for GeoJSON Point
    latitude = scraped.get("latitude")
    longitude = scraped.get("longitude")
    
    # Start with scraped data as base
    merged = {
        "station_id": station_id,  # int
        "internal_id": internal_id,
        "name": scraped.get("name"),
        "status": scraped.get("status"),
        "note": scraped.get("note"),
        "fast_charging": scraped.get("fast_charging"),
        "opening_hours_string": scraped.get("opening_hours_string"),
        "is_non_stop": scraped.get("is_non_stop"),
        "station_service": scraped.get("station_service"),
        "charging_slots": scraped.get("charging_slots"),
        "fast_charging_slots": scraped.get("fast_charging_slots"),
        "parking_slots": scraped.get("parking_slots"),
        "latitude": latitude,
        "longitude": longitude,
        "address": address,  # String from location.address
        "chargers": scraped.get("chargers", []),
        "cables": scraped.get("cables", []),
        "providers": scraped.get("providers", []),
        "manufacturer": scraped.get("manufacturer"),
        "date_changed": scraped.get("date_changed"),
        "last_merged": now
    }
    
    # Add GeoJSON Point location for 2dsphere index (if latitude/longitude exist)
    if latitude is not None and longitude is not None:
        merged["location"] = {
            "type": "Point",
            "coordinates": [float(longitude), float(latitude)]  # [longitude, latitude] - GeoJSON format
        }
    
    # Track timestamps for each field from scraped data
    scraped_timestamps = {}
    trackable_fields = [
        "name", "status", "note",
        "fast_charging", "opening_hours_string", "is_non_stop", "station_service",
        "charging_slots", "fast_charging_slots", "parking_slots",
        "latitude", "longitude", "location",  # location for address tracking
        "chargers", "cables", "providers", "manufacturer"
    ]
    
    for field in trackable_fields:
        field_updated_at = scraped.get(f"{field}_updated_at")
        if field_updated_at:
            scraped_timestamps[field] = field_updated_at
        else:
            # For fields without timestamp, use min datetime (scraped data wins only if user change is older)
            scraped_timestamps[field] = datetime.min
    
    # Special handling: location_updated_at tracks address changes (from location.address)
    location_updated_at = scraped.get("location_updated_at")
    if location_updated_at:
        scraped_timestamps["location"] = location_updated_at  # For address tracking
    
    # Latitude and longitude have their own timestamps
    lat_updated_at = scraped.get("latitude_updated_at")
    if lat_updated_at:
        scraped_timestamps["latitude"] = lat_updated_at
    
    lon_updated_at = scraped.get("longitude_updated_at")
    if lon_updated_at:
        scraped_timestamps["longitude"] = lon_updated_at
    
    # Process user changes chronologically
    for user_change in user_changes:
        patch = user_change.get("patch", {})
        change_timestamp = user_change.get("timestamp")
        if not change_timestamp:
            continue
        
        # Process station fields (for charging stations, patch structure may be different)
        # Check if patch has direct fields or nested "station" object
        station_patch = patch.get("station", {})
        if not station_patch:
            # If no "station" key, assume patch fields are at top level
            station_patch = patch
        
        for field, value in station_patch.items():
            # Skip timestamp fields (they end with "_timestamp")
            if field.endswith("_timestamp"):
                continue
                
            # Skip non-station fields (they are handled separately)
            if field in ["chargers", "cables", "providers"]:
                continue
            
            # Map field names if needed
            mapped_field = field
            if field == "location":
                # Handle location separately with field-level timestamps
                location = value
                if location:
                    if isinstance(location, dict):
                        # Update address from location.address
                        if "address" in location and location["address"] is not None:
                            field_timestamp = location.get("address_timestamp")
                            if field_timestamp:
                                try:
                                    field_ts = datetime.fromisoformat(field_timestamp.replace('Z', '+00:00'))
                                except:
                                    field_ts = change_timestamp
                            else:
                                field_ts = change_timestamp
                            if field_ts > scraped_timestamps.get("location", datetime.min):
                                merged["address"] = location["address"]
                        # Update latitude/longitude from location
                        if "lat" in location and location["lat"] is not None:
                            field_timestamp = location.get("lat_timestamp")
                            if field_timestamp:
                                try:
                                    field_ts = datetime.fromisoformat(field_timestamp.replace('Z', '+00:00'))
                                except:
                                    field_ts = change_timestamp
                            else:
                                field_ts = change_timestamp
                            if field_ts > scraped_timestamps.get("latitude", datetime.min):
                                merged["latitude"] = location["lat"]
                                # Update location GeoJSON Point if latitude changed
                                if merged.get("longitude") is not None:
                                    merged["location"] = {
                                        "type": "Point",
                                        "coordinates": [float(merged["longitude"]), float(location["lat"])]
                                    }
                        if "lon" in location and location["lon"] is not None:
                            field_timestamp = location.get("lon_timestamp")
                            if field_timestamp:
                                try:
                                    field_ts = datetime.fromisoformat(field_timestamp.replace('Z', '+00:00'))
                                except:
                                    field_ts = change_timestamp
                            else:
                                field_ts = change_timestamp
                            if field_ts > scraped_timestamps.get("longitude", datetime.min):
                                merged["longitude"] = location["lon"]
                                # Update location GeoJSON Point if longitude changed
                                if merged.get("latitude") is not None:
                                    merged["location"] = {
                                        "type": "Point",
                                        "coordinates": [float(location["lon"]), float(merged["latitude"])]
                                    }
                continue
            
            # Standard field mapping (only for fields that exist in merged structure)
            # Note: skip url, refreshment_venues, payment_methods, opening_hours (not in merged)
            if mapped_field in ["name", "status", "note", "fast_charging", "opening_hours_string", 
                               "is_non_stop", "station_service", "charging_slots", 
                               "fast_charging_slots", "parking_slots"]:
                # Get field-level timestamp if available, otherwise use change_timestamp
                field_timestamp_key = f"{field}_timestamp"
                field_timestamp = station_patch.get(field_timestamp_key)
                if field_timestamp:
                    try:
                        # Parse ISO 8601 timestamp
                        field_ts = datetime.fromisoformat(field_timestamp.replace('Z', '+00:00'))
                    except:
                        field_ts = change_timestamp
                else:
                    field_ts = change_timestamp
                
                # Use user change if it's newer than scraped data
                if field_ts > scraped_timestamps.get(mapped_field, datetime.min):
                    merged[mapped_field] = value
        
        # Process chargers array
        chargers_patch = patch.get("chargers")
        if chargers_patch is not None:
            # Check if any charger has a timestamp (use the most recent one)
            max_charger_timestamp = change_timestamp
            for charger in chargers_patch:
                if isinstance(charger, dict):
                    charger_ts_str = charger.get("timestamp")
                    if charger_ts_str:
                        try:
                            charger_ts = datetime.fromisoformat(charger_ts_str.replace('Z', '+00:00'))
                            if charger_ts > max_charger_timestamp:
                                max_charger_timestamp = charger_ts
                        except:
                            pass
            
            if max_charger_timestamp > scraped_timestamps.get("chargers", datetime.min):
                merged["chargers"] = chargers_patch
        
        # Process cables array
        cables_patch = patch.get("cables")
        if cables_patch is not None:
            if change_timestamp > scraped_timestamps.get("cables", datetime.min):
                merged["cables"] = cables_patch
        
        # Process providers array
        providers_patch = patch.get("providers")
        if providers_patch is not None:
            if change_timestamp > scraped_timestamps.get("providers", datetime.min):
                merged["providers"] = providers_patch
    
    return merged


if __name__ == "__main__":
    update_merged_charging_stations()

