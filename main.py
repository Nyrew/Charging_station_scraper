"""
Main orchestrator for Charging Station Scraper
"""

import argparse
import logging
import os
import sys
from typing import Dict

from alerting import send_alert
from config import Config
from logger import logger
from scraper import ChargingStationScraper
from database.postgres_import import import_charging_station_data
from validators import ChargingStationValidator

logging.getLogger().setLevel(getattr(logging, Config.get_log_level().upper()))


def scrape_and_import(full_import: bool = False) -> Dict:
    """
    Scrape data and import to MongoDB.

    Args:
        full_import: If True, delete all existing data and do a full re-import.
                     For regular updates use False (incremental).
    """
    if full_import:
        logger.warning("Full import mode — ALL EXISTING DATA WILL BE DELETED")
        logger.warning("Use only for initial import or data repair")

    try:
        scraper = ChargingStationScraper()

        logger.info("Starting scraping process")
        data = scraper.scrape_all()

        logger.info("Validating data")
        station_validation = ChargingStationValidator.validate_stations(data["stations"])
        metadata_validation = ChargingStationValidator.validate_metadata(data["metadata"])

        logger.info(
            f"Validation: {station_validation['valid']}/{station_validation['total']} stations valid"
        )
        if station_validation["invalid"] > 0:
            logger.warning(f"{station_validation['invalid']} invalid stations found")
            for error in station_validation["errors"][:10]:
                logger.warning(f"Invalid station {error['station_id']}: {error['error']}")

        for key, val in metadata_validation.items():
            logger.info(f"Metadata {key}: {val['valid']}/{val['total']} valid")
            if val["invalid"] > 0:
                logger.warning(f"{val['invalid']} invalid {key} found")

        valid_stations = [
            s for s in data["stations"]
            if ChargingStationValidator.validate_station(s)[0]
        ]
        data["stations"] = valid_stations
        logger.info(f"Using {len(valid_stations)} valid stations for import")

        # Alert if unexpectedly few stations
        min_stations = int(os.getenv("ALERT_MIN_STATIONS", "100"))
        if len(valid_stations) < min_stations:
            send_alert(
                "Low station count after validation",
                f"Only {len(valid_stations)} valid stations (threshold: {min_stations}). "
                "Possible API structure change.",
                level="warning",
            )

        logger.info("Importing to MongoDB")
        results = import_charging_station_data(data, full_import=full_import)

        try:
            logger.info("Updating merged_charging_stations collection")
            from database.postgres_update_merged import update_merged_charging_stations
            update_merged_charging_stations()
            logger.info("Merged collections updated")
        except Exception as e:
            logger.warning(f"Failed to update merged collections: {e}")

        logger.info(f"Import results: {results}")
        return results

    except Exception as e:
        logger.error(f"Scraping/import failed: {e}", exc_info=True)
        send_alert("Scraping/import failed", str(e))
        sys.exit(1)


def test_connection() -> bool:
    """Test MongoDB connection."""
    try:
        from database.postgres_import import ChargingStationMongoDBImporter
        importer = ChargingStationMongoDBImporter()
        if importer.test_connection():
            logger.info("MongoDB connection successful")
            stats = importer.get_collection_stats()
            logger.info(f"Collection stats: {stats}")
            importer.close_connection()
            return True
        logger.error("MongoDB connection failed")
        return False
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False


def create_indexes() -> bool:
    """Create MongoDB indexes."""
    try:
        from database.postgres_import import ChargingStationMongoDBImporter
        importer = ChargingStationMongoDBImporter()
        if not importer.test_connection():
            logger.error("MongoDB connection failed")
            return False
        importer.create_indexes()
        importer.close_connection()
        return True
    except Exception as e:
        logger.error(f"Failed to create indexes: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Charging Station Scraper")
    parser.add_argument(
        "--task",
        required=True,
        choices=["scrape", "scrape_full", "test_connection", "create_indexes"],
        help="Task: scrape (incremental), scrape_full (full import), test_connection, create_indexes",
    )
    args = parser.parse_args()

    env_full_import = os.getenv("FULL_IMPORT", "false").strip().lower() in {"1", "true", "yes"}

    if args.task == "test_connection":
        sys.exit(0 if test_connection() else 1)
    elif args.task == "create_indexes":
        sys.exit(0 if create_indexes() else 1)
    elif args.task == "scrape":
        scrape_and_import(full_import=env_full_import)
    elif args.task == "scrape_full":
        scrape_and_import(full_import=True)
    else:
        logger.error(f"Unknown task: {args.task!r}")
        sys.exit(1)
