"""
Configuration module for Charging Station Scraper
Loads environment variables safely from .env file or environment
"""

import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def load_env_file():
    """Load .env file if it exists."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        try:
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        # Only set if not already in environment
                        if key.strip() not in os.environ:
                            os.environ[key.strip()] = value.strip()
            logger.info("✅ Loaded environment variables from .env file")
        except Exception as e:
            logger.warning(f"⚠️ Could not load .env file: {e}")
    else:
        logger.info("ℹ️ No .env file found, using system environment variables")

# Load .env file on import
load_env_file()

class Config:
    """Configuration class for the application."""
    
    @staticmethod
    def get_mongodb_uri() -> str:
        """Get MongoDB connection URI."""
        uri = os.getenv('MONGODB_URI')
        if not uri:
            raise ValueError(
                "❌ MONGODB_URI environment variable not set! "
                "Please create a .env file with your MongoDB connection string."
            )
        return uri
    
    @staticmethod
    def get_mongodb_database() -> str:
        """Get MongoDB database name."""
        return os.getenv('MONGODB_DATABASE', 'fueldb')
    
    @staticmethod
    def get_charging_stations_collection() -> str:
        """Get MongoDB collection name for charging stations."""
        return os.getenv('CHARGING_STATIONS_COLLECTION', 'charging_stations')
    
    @staticmethod
    def get_providers_collection() -> str:
        """Get MongoDB collection name for providers."""
        return os.getenv('PROVIDERS_COLLECTION', 'charging_providers')
    
    @staticmethod
    def get_manufacturers_collection() -> str:
        """Get MongoDB collection name for manufacturers."""
        return os.getenv('MANUFACTURERS_COLLECTION', 'charging_manufacturers')
    
    @staticmethod
    def get_charger_types_collection() -> str:
        """Get MongoDB collection name for charger types."""
        return os.getenv('CHARGER_TYPES_COLLECTION', 'charging_charger_types')
    
    @staticmethod
    def get_payment_methods_collection() -> str:
        """Get MongoDB collection name for payment methods."""
        return os.getenv('PAYMENT_METHODS_COLLECTION', 'charging_payment_methods')
    
    @staticmethod
    def get_database_url() -> Optional[str]:
        """Get PostgreSQL database URL. SUPABASE_URL takes priority to avoid
        collision with Railway's auto-injected DATABASE_URL (direct connection)."""
        return os.getenv("SUPABASE_URL") or os.getenv("DATABASE_URL")

    @staticmethod
    def get_api_url() -> str:
        """Get API URL for charging stations data."""
        return os.getenv('CHARGING_STATIONS_API_URL', 'https://fdrive.cz/data/export/pub/charging-stations-geo.json')
    
    @staticmethod
    def get_log_level() -> str:
        """Get logging level."""
        return os.getenv('LOG_LEVEL', 'INFO')
    
    @staticmethod
    def is_development() -> bool:
        """Check if running in development mode."""
        return os.getenv('ENVIRONMENT', 'production').lower() in ['dev', 'development', 'local']
    
    @staticmethod
    def get_data_directory() -> str:
        """Get data directory path."""
        if os.path.exists("/app/data"):
            return "/app/data"
        elif Config.is_development():
            return "."
        else:
            return "/tmp"

