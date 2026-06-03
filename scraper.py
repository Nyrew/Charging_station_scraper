"""
Charging Station Scraper
Downloads data from fdrive.cz API and returns structured data
"""

import json
import logging
import os
from typing import Dict, List, Optional

import requests

from config import Config
from http_utils import backoff_delay, get_random_headers

logger = logging.getLogger(__name__)


class ChargingStationScraper:
    """Scraper for charging station data from fdrive.cz API."""
    
    def __init__(self, api_url: Optional[str] = None):
        """
        Initialize scraper.
        
        Args:
            api_url: Optional API URL. If not provided, uses config default.
        """
        self.api_url = api_url or Config.get_api_url()
    
    def fetch_data(self) -> Dict:
        """
        Fetch data from API with retry and exponential backoff.

        Returns:
            Dictionary with GeoJSON data including features and metadata

        Raises:
            requests.RequestException: If all attempts fail
        """
        max_attempts = int(os.getenv("MAX_FETCH_ATTEMPTS", "3"))

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Fetching data (attempt {attempt}/{max_attempts}): {self.api_url}")
                response = requests.get(self.api_url, headers=get_random_headers(), timeout=60)
                response.raise_for_status()

                data = response.json()
                station_count = len(data.get("features", []))
                logger.info(f"Fetched {station_count} stations")
                return data

            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error (not retrying): {e}")
                raise
            except requests.RequestException as e:
                logger.warning(f"Attempt {attempt} failed: {e}")
                if attempt < max_attempts:
                    backoff_delay(attempt)

        raise requests.RequestException(f"All {max_attempts} fetch attempts failed for {self.api_url}")
    
    def parse_stations(self, data: Dict) -> List[Dict]:
        """
        Parse station features from GeoJSON data.
        
        Args:
            data: GeoJSON data dictionary
            
        Returns:
            List of station dictionaries
        """
        stations = []
        features = data.get('features', [])
        
        for feature in features:
            try:
                station = self._parse_station_feature(feature)
                if station:
                    stations.append(station)
            except Exception as e:
                logger.warning(f"Failed to parse station feature: {e}")
                continue

        logger.info(f"Parsed {len(stations)} stations")
        return stations
    
    def _parse_station_feature(self, feature: Dict) -> Optional[Dict]:
        """
        Parse a single station feature.
        
        Args:
            feature: GeoJSON feature dictionary
            
        Returns:
            Parsed station dictionary or None if invalid
        """
        if not feature.get('properties') or not feature.get('geometry'):
            return None
        
        props = feature['properties']
        geometry = feature['geometry']
        
        # Extract coordinates (GeoJSON format: [lon, lat])
        coordinates = geometry.get('coordinates', [])
        if len(coordinates) != 2:
            return None
        
        lon, lat = coordinates[0], coordinates[1]
        
        # Build station document
        station = {
            'station_id': int(props.get('id', 0)) if props.get('id') else None,
            'name': props.get('name', ''),
            'url': props.get('url', ''),
            'status': props.get('status', 'unknown'),
            'fast_charging': props.get('fast_charging', False),
            'opening_hours_string': props.get('opening_hours_string', ''),
            'charging_slots': props.get('charging_slots', 0),
            'fast_charging_slots': props.get('fast_charging_slots', 0),
            'parking_slots': props.get('parking_slots', 0),
            'station_service': props.get('station_service', ''),
            'refreshment_venues': props.get('refreshment_venues', ''),
            'is_non_stop': props.get('is_non_stop', False),
            'note': props.get('note', ''),
            'date_changed': props.get('date_changed', ''),
            'location': {
                'address': props.get('location', {}).get('address', ''),
                'country': props.get('location', {}).get('country', 'cz'),
                'coordinates': {
                    'type': 'Point',
                    'coordinates': [lon, lat]
                }
            },
            'latitude': lat,
            'longitude': lon,
            'providers': props.get('providers', []),
            'chargers': props.get('chargers', []),
            'cables': props.get('cables', []),
            'payment_methods': props.get('payment_methods', []),
            # 'pics' intentionally excluded - not stored in DB
            'opening_hours': props.get('opening_hours', []),
            'manufacturer': props.get('manufacturer')
        }
        
        return station
    
    def parse_metadata(self, data: Dict) -> Dict[str, List[Dict]]:
        """
        Parse metadata (providers, manufacturers, charger_types, payment_methods).
        
        Args:
            data: GeoJSON data dictionary
            
        Returns:
            Dictionary with metadata lists
        """
        metadata = {
            'providers': [],
            'manufacturers': [],
            'charger_types': [],
            'payment_methods': []
        }
        
        # Parse providers
        providers = data.get('providers', {})
        for provider_id, provider_data in providers.items():
            metadata['providers'].append({
                'provider_id': str(provider_id),
                'name': provider_data.get('name', ''),
                'url': provider_data.get('url', ''),
                'tel': provider_data.get('tel', ''),
                'show': provider_data.get('show', True)
            })
        
        # Parse manufacturers
        manufacturers = data.get('manufacturers', {})
        for manufacturer_id, manufacturer_data in manufacturers.items():
            metadata['manufacturers'].append({
                'manufacturer_id': str(manufacturer_id),
                'name': manufacturer_data.get('name', '')
            })
        
        # Parse charger_types
        charger_types = data.get('charger_types', {})
        for charger_type_id, charger_type_data in charger_types.items():
            metadata['charger_types'].append({
                'charger_type_id': str(charger_type_id),
                'name': charger_type_data.get('name', ''),
                'is_fast': charger_type_data.get('is_fast', False),
                'current_type': charger_type_data.get('current_type', ''),
                'order': charger_type_data.get('order', 0),
                'show': charger_type_data.get('show', True)
            })
        
        # Parse payment_methods
        payment_methods = data.get('payment_methods', {})
        for payment_method_id, payment_method_data in payment_methods.items():
            metadata['payment_methods'].append({
                'payment_method_id': str(payment_method_id),
                'name': payment_method_data.get('name', ''),
                'is_free': payment_method_data.get('is_free', False),
                'order': payment_method_data.get('order', 0)
            })
        
        logger.info(
            f"Parsed metadata: {len(metadata['providers'])} providers, "
            f"{len(metadata['manufacturers'])} manufacturers, "
            f"{len(metadata['charger_types'])} charger types, "
            f"{len(metadata['payment_methods'])} payment methods"
        )
        
        return metadata
    
    def scrape_all(self) -> Dict[str, any]:
        """
        Scrape all data (stations + metadata).
        
        Returns:
            Dictionary with 'stations' and 'metadata' keys
        """
        data = self.fetch_data()
        
        stations = self.parse_stations(data)
        metadata = self.parse_metadata(data)
        
        return {
            'stations': stations,
            'metadata': metadata
        }

