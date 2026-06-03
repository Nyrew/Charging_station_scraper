"""
Data validators for charging station data
"""

from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class ChargingStationValidator:
    """Validator for charging station data."""
    
    @staticmethod
    def validate_station(station: Dict) -> Tuple[bool, Optional[str]]:
        """
        Validate a station record.
        
        Args:
            station: Station dictionary
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Required fields
        required_fields = ['station_id', 'name']
        for field in required_fields:
            if not station.get(field):
                return False, f"Missing required field: {field}"
        
        # Validate coordinates
        lat = station.get('latitude')
        lon = station.get('longitude')
        
        if lat is None or lon is None:
            return False, "Missing coordinates (latitude/longitude)"
        
        # Validate coordinate ranges
        if not (-90 <= lat <= 90):
            return False, f"Invalid latitude: {lat} (must be between -90 and 90)"
        
        if not (-180 <= lon <= 180):
            return False, f"Invalid longitude: {lon} (must be between -180 and 180)"
        
        # Validate numeric fields
        numeric_fields = ['charging_slots', 'fast_charging_slots', 'parking_slots']
        for field in numeric_fields:
            value = station.get(field)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                return False, f"Invalid {field}: {value} (must be non-negative number)"
        
        return True, None
    
    @staticmethod
    def validate_provider(provider: Dict) -> Tuple[bool, Optional[str]]:
        """Validate a provider record."""
        if not provider.get('provider_id'):
            return False, "Missing provider_id"
        if not provider.get('name'):
            return False, "Missing name"
        return True, None
    
    @staticmethod
    def validate_manufacturer(manufacturer: Dict) -> Tuple[bool, Optional[str]]:
        """Validate a manufacturer record."""
        if not manufacturer.get('manufacturer_id'):
            return False, "Missing manufacturer_id"
        if not manufacturer.get('name'):
            return False, "Missing name"
        return True, None
    
    @staticmethod
    def validate_charger_type(charger_type: Dict) -> Tuple[bool, Optional[str]]:
        """Validate a charger type record."""
        if not charger_type.get('charger_type_id'):
            return False, "Missing charger_type_id"
        if not charger_type.get('name'):
            return False, "Missing name"
        return True, None
    
    @staticmethod
    def validate_payment_method(payment_method: Dict) -> Tuple[bool, Optional[str]]:
        """Validate a payment method record."""
        if not payment_method.get('payment_method_id'):
            return False, "Missing payment_method_id"
        if not payment_method.get('name'):
            return False, "Missing name"
        return True, None
    
    @staticmethod
    def validate_stations(stations: List[Dict]) -> Dict[str, any]:
        """
        Validate all stations and return statistics.
        
        Args:
            stations: List of station dictionaries
            
        Returns:
            Dictionary with validation statistics
        """
        valid_count = 0
        invalid_count = 0
        errors = []
        
        for station in stations:
            is_valid, error_msg = ChargingStationValidator.validate_station(station)
            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1
                errors.append({
                    'station_id': station.get('station_id', 'unknown'),
                    'error': error_msg
                })
        
        return {
            'total': len(stations),
            'valid': valid_count,
            'invalid': invalid_count,
            'errors': errors
        }
    
    @staticmethod
    def validate_metadata(metadata: Dict) -> Dict[str, any]:
        """
        Validate all metadata and return statistics.
        
        Args:
            metadata: Dictionary with metadata lists
            
        Returns:
            Dictionary with validation statistics
        """
        results = {}
        
        # Validate providers
        if 'providers' in metadata:
            providers = metadata['providers']
            valid = sum(1 for p in providers if ChargingStationValidator.validate_provider(p)[0])
            results['providers'] = {
                'total': len(providers),
                'valid': valid,
                'invalid': len(providers) - valid
            }
        
        # Validate manufacturers
        if 'manufacturers' in metadata:
            manufacturers = metadata['manufacturers']
            valid = sum(1 for m in manufacturers if ChargingStationValidator.validate_manufacturer(m)[0])
            results['manufacturers'] = {
                'total': len(manufacturers),
                'valid': valid,
                'invalid': len(manufacturers) - valid
            }
        
        # Validate charger_types
        if 'charger_types' in metadata:
            charger_types = metadata['charger_types']
            valid = sum(1 for ct in charger_types if ChargingStationValidator.validate_charger_type(ct)[0])
            results['charger_types'] = {
                'total': len(charger_types),
                'valid': valid,
                'invalid': len(charger_types) - valid
            }
        
        # Validate payment_methods
        if 'payment_methods' in metadata:
            payment_methods = metadata['payment_methods']
            valid = sum(1 for pm in payment_methods if ChargingStationValidator.validate_payment_method(pm)[0])
            results['payment_methods'] = {
                'total': len(payment_methods),
                'valid': valid,
                'invalid': len(payment_methods) - valid
            }
        
        return results

