"""
ID Map Manager - správa mapování mezi internal_id a source_id
Vytváří a spravuje kolekci id_map pro unifikované ID napříč všemi zdroji dat.
"""

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime
from typing import Dict, Optional, List
import logging
from config import Config

logger = logging.getLogger(__name__)


class IdMapManager:
    """Manager pro správu ID mapování."""
    
    def __init__(self, client: Optional[MongoClient] = None):
        """
        Initialize IdMapManager.
        
        Args:
            client: Optional MongoDB client. If not provided, creates new connection.
        """
        if client:
            self.client = client
            self.own_client = False
        else:
            self.uri = Config.get_mongodb_uri()
            self.client = MongoClient(self.uri, server_api=ServerApi('1'))
            self.own_client = True
            
        self.db = self.client[Config.get_mongodb_database()]
        self.id_map_collection = self.db["id_map"]
        self.counters_collection = self.db["counters"]
        
        # Ensure counter exists
        self._initialize_counter()
        self._create_indexes()
    
    def _initialize_counter(self):
        """Initialize the counter for internal_id if it doesn't exist."""
        if not self.counters_collection.find_one({"_id": "internal_id"}):
            self.counters_collection.insert_one({
                "_id": "internal_id",
                "sequence_value": 0
            })
            logger.info("✅ Initialized internal_id counter")
    
    def _create_indexes(self):
        """Create indexes for id_map collection."""
        try:
            # Unique index on source + source_id combination
            self.id_map_collection.create_index(
                [("source", 1), ("source_id", 1)],
                unique=True,
                name="source_source_id_unique"
            )
            # Index on internal_id for fast lookups
            self.id_map_collection.create_index("internal_id", unique=True, name="internal_id_unique")
            # Index on source for filtering
            self.id_map_collection.create_index("source", name="source_index")
            logger.info("✅ Created indexes for id_map collection")
        except Exception as e:
            # Ignore if indexes already exist
            error_msg = str(e)
            if "already exists" in error_msg.lower() or "IndexOptionsConflict" in error_msg:
                logger.debug(f"Indexes already exist for id_map collection")
            else:
                logger.warning(f"⚠️ Could not create indexes: {e}")
    
    def _get_next_internal_id(self) -> int:
        """
        Get next incremental internal_id.
        
        Returns:
            Next internal_id as integer
        """
        result = self.counters_collection.find_one_and_update(
            {"_id": "internal_id"},
            {"$inc": {"sequence_value": 1}},
            return_document=True
        )
        return result["sequence_value"]
    
    def get_or_create_internal_id(self, source: str, source_id) -> int:
        """
        Get existing internal_id or create new one for given source and source_id.
        
        Args:
            source: Source type ("scrape_fuel", "scrape_charging", "app")
            source_id: ID from source system (int for scrape_*, string for app)
            
        Returns:
            internal_id as integer
        """
        # Convert source_id to appropriate type
        # For scrape_fuel and scrape_charging, convert to int
        # For app, keep as string (but we'll try to convert to int if possible)
        if source in ["scrape_fuel", "scrape_charging"]:
            try:
                source_id_int = int(source_id) if not isinstance(source_id, int) else source_id
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Cannot convert source_id to int for {source}: {source_id}, keeping as string")
                source_id_int = source_id
        else:
            # For "app" source, try to convert to int if it's numeric, otherwise keep as string
            try:
                source_id_int = int(source_id) if not isinstance(source_id, int) else source_id
            except (ValueError, TypeError):
                # For app source with non-numeric IDs (e.g., "app_1234567890"), keep as string
                source_id_int = str(source_id)
        
        # Check if mapping already exists
        existing = self.id_map_collection.find_one({
            "source": source,
            "source_id": source_id_int
        })
        
        if existing:
            # Update last_seen
            now = datetime.utcnow()
            self.id_map_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"last_seen": now}}
            )
            return existing["internal_id"]
        
        # Create new mapping
        internal_id = self._get_next_internal_id()
        now = datetime.utcnow()
        
        self.id_map_collection.insert_one({
            "internal_id": internal_id,
            "source": source,
            "source_id": source_id_int,
            "first_seen": now,
            "last_seen": now
        })
        
        logger.debug(f"Created new mapping: internal_id={internal_id}, source={source}, source_id={source_id_int}")
        return internal_id
    
    def get_internal_id(self, source: str, source_id) -> Optional[int]:
        """
        Get internal_id for given source and source_id (without creating new).
        
        Args:
            source: Source type
            source_id: ID from source system (int for scrape_*, string for app)
            
        Returns:
            internal_id if exists, None otherwise
        """
        # Convert source_id to appropriate type
        if source in ["scrape_fuel", "scrape_charging"]:
            try:
                source_id_int = int(source_id) if not isinstance(source_id, int) else source_id
            except (ValueError, TypeError):
                source_id_int = source_id
        else:
            try:
                source_id_int = int(source_id) if not isinstance(source_id, int) else source_id
            except (ValueError, TypeError):
                source_id_int = str(source_id)
        
        mapping = self.id_map_collection.find_one({
            "source": source,
            "source_id": source_id_int
        })
        return mapping["internal_id"] if mapping else None
    
    def populate_from_existing_data(self) -> Dict[str, int]:
        """
        Populate id_map from existing charging_stations collection.
        
        Returns:
            Dictionary with counts: {"charging": count}
        """
        charging_collection_name = Config.get_charging_stations_collection()
        charging_collection = self.db[charging_collection_name]
        
        counts = {"charging": 0}
        
        # Process charging stations
        logger.info("Processing charging stations...")
        charging_stations = charging_collection.find({}, {"station_id": 1})
        for station in charging_stations:
            station_id = station.get("station_id")
            if station_id:
                try:
                    # station_id is already int in DB, but handle both cases
                    station_id_int = int(station_id) if not isinstance(station_id, int) else station_id
                    self.get_or_create_internal_id("scrape_charging", station_id_int)
                    counts["charging"] += 1
                except Exception as e:
                    logger.warning(f"Error processing charging station {station_id}: {e}")
        
        logger.info(f"✅ Populated id_map: {counts['charging']} charging stations")
        return counts
    
    def close_connection(self):
        """Close MongoDB connection if we own it."""
        if self.own_client:
            self.client.close()
            logger.info("Closed MongoDB connection")

