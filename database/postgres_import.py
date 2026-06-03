"""
PostgreSQL import module for charging station data.
Drop-in replacement for mongodb_import.py — identical public API.

Writes to: charging_stations, charging_providers, charging_manufacturers,
           charging_charger_types, charging_payment_methods, id_map, info_import
"""

import json
import time
from datetime import datetime
from typing import Dict, List, Optional

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

from config import Config
from database.postgres_id_map_manager import PostgresIdMapManager
from database.postgres_import_logger import PostgresImportLogger

import logging
logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_int(val) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (ValueError, TypeError):
        return None

def _to_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None

def _j(val) -> Optional[Json]:
    """Wrap value for JSONB column. Returns None for empty/None values."""
    if val is None:
        return None
    return Json(val)

def _int_list(val) -> Optional[list]:
    """Convert a list of values to a list of ints, or None if empty/None."""
    if not val:
        return None
    try:
        result = [int(v) for v in val if v is not None]
        return result if result else None
    except (ValueError, TypeError):
        return None


# ── columns written to charging_stations (mirrors DDL) ───────────────────────

_STATION_COLS = [
    "station_id", "name", "url", "status", "fast_charging",
    "opening_hours_string", "charging_slots", "fast_charging_slots", "parking_slots",
    "station_service", "refreshment_venues", "is_non_stop", "note", "date_changed",
    "lat", "lon", "address", "manufacturer",
    "providers", "payment_methods", "chargers", "cables", "opening_hours",
    "import_timestamp", "import_date",
]

# Fields compared for change detection
_COMPARE_FIELDS = [
    "name", "url", "status", "fast_charging", "opening_hours_string",
    "charging_slots", "fast_charging_slots", "parking_slots",
    "station_service", "refreshment_venues", "is_non_stop", "note",
    "date_changed", "lat", "lon", "address", "manufacturer",
    "providers", "payment_methods",
]


class ChargingStationPostgresImporter:
    """Imports charging station data into Supabase (PostgreSQL)."""

    def __init__(self) -> None:
        url = Config.get_database_url()
        if not url:
            raise ValueError("DATABASE_URL environment variable is not set")
        self.conn = psycopg2.connect(url)
        self.conn.autocommit = False
        self.import_logger = PostgresImportLogger(self.conn)
        self.id_map_manager = PostgresIdMapManager(self.conn)

    # ── connection ──────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
            logger.info("✅ PostgreSQL connection successful")
            return True
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            return False

    def close_connection(self) -> None:
        try:
            self.conn.close()
            logger.info("📪 PostgreSQL connection closed")
        except Exception as e:
            logger.error(f"❌ Error closing connection: {e}")

    # ── normalization ─────────────────────────────────────────────────────

    def _normalize_station(self, station: Dict) -> Optional[Dict]:
        """Map scraper fields to charging_stations column names."""
        station_id = _to_int(station.get("station_id"))
        if station_id is None:
            return None

        location = station.get("location") or {}
        if isinstance(location, dict):
            address = location.get("address") or None
        else:
            address = None

        now = datetime.utcnow()
        return {
            "station_id":              station_id,
            "name":                    station.get("name") or None,
            "url":                     station.get("url") or None,
            "status":                  station.get("status") or None,
            "fast_charging":           bool(station.get("fast_charging", False)),
            "opening_hours_string":    station.get("opening_hours_string") or None,
            "charging_slots":          _to_int(station.get("charging_slots")),
            "fast_charging_slots":     _to_int(station.get("fast_charging_slots")),
            "parking_slots":           _to_int(station.get("parking_slots")),
            "station_service":         station.get("station_service") or None,
            "refreshment_venues":      station.get("refreshment_venues") or None,
            "is_non_stop":             bool(station.get("is_non_stop", False)),
            "note":                    station.get("note") or None,
            "date_changed":            station.get("date_changed") or None,
            "lat":                     _to_float(station.get("latitude")),   # scraper uses latitude
            "lon":                     _to_float(station.get("longitude")),  # scraper uses longitude
            "address":                 address,
            "manufacturer":            _to_int(station.get("manufacturer")),
            "providers":               _int_list(station.get("providers")),
            "payment_methods":         _int_list(station.get("payment_methods")),
            "chargers":                _j(station.get("chargers")),
            "cables":                  _j(station.get("cables")),
            "opening_hours":           _j(station.get("opening_hours")),
            "import_timestamp":        now,
            "import_date":             now.strftime("%d.%m.%Y"),
        }

    def _station_row(self, nd: Dict) -> list:
        return [nd.get(c) for c in _STATION_COLS]

    def _get_changed_fields(self, new_data: Dict, existing: Dict) -> List[str]:
        return [f for f in _COMPARE_FIELDS if new_data.get(f) != existing.get(f)]

    # ── station import ────────────────────────────────────────────────────

    def import_stations(self, stations: List[Dict], full_import: bool = False) -> Dict[str, int]:
        """
        Import stations. full_import=True wipes and re-inserts.
        full_import=False does incremental upsert via ON CONFLICT.
        """
        t0 = time.time()
        stats: Dict[str, int] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}

        normalized: List[Dict] = []
        for s in stations:
            try:
                nd = self._normalize_station(s)
                if nd:
                    normalized.append(nd)
                else:
                    stats["skipped"] += 1
            except Exception as e:
                logger.warning(f"⚠️ Normalize error for station {s.get('station_id')}: {e}")
                stats["errors"] += 1

        try:
            with self.conn.cursor() as cur:
                if full_import:
                    cur.execute("DELETE FROM charging_stations")
                    stats["deleted"] = cur.rowcount
                    logger.info(f"🗑️ Deleted {stats['deleted']} charging stations")

                if full_import:
                    rows = [self._station_row(nd) for nd in normalized]
                    if rows:
                        cols = ", ".join(_STATION_COLS)
                        psycopg2.extras.execute_values(
                            cur,
                            f"INSERT INTO charging_stations ({cols}) VALUES %s ON CONFLICT (station_id) DO NOTHING",
                            rows,
                            page_size=200,
                        )
                        stats["inserted"] = len(rows)
                else:
                    # Incremental: INSERT ... ON CONFLICT DO UPDATE
                    cols = ", ".join(_STATION_COLS)
                    update_set = ", ".join(
                        f"{c} = EXCLUDED.{c}"
                        for c in _STATION_COLS
                        if c != "station_id"
                    )
                    rows = [self._station_row(nd) for nd in normalized]
                    if rows:
                        result_rows = []
                        psycopg2.extras.execute_values(
                            cur,
                            f"""
                            INSERT INTO charging_stations ({cols}) VALUES %s
                            ON CONFLICT (station_id) DO UPDATE SET {update_set}
                            RETURNING (xmax = 0) AS is_new
                            """,
                            rows,
                            page_size=200,
                        )
                        inserted_rows = cur.fetchall()
                        for row in inserted_rows:
                            if row[0]:
                                stats["inserted"] += 1
                            else:
                                stats["updated"] += 1

                # Update id_map
                for nd in normalized:
                    try:
                        self.id_map_manager.get_or_create_internal_id(
                            "scrape_charging", nd["station_id"]
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ id_map update failed for station {nd['station_id']}: {e}")

            self.conn.commit()

        except Exception as e:
            self.conn.rollback()
            logger.error(f"❌ Station import transaction failed: {e}")
            duration = time.time() - t0
            self.import_logger.log_import(
                "charging_stations",
                "full_import" if full_import else "incremental_upsert",
                errors=len(stations), duration=duration, status="failed",
                error_message=str(e),
            )
            raise

        duration = time.time() - t0
        self.import_logger.log_import(
            "charging_stations",
            "full_import" if full_import else "incremental_upsert",
            inserted=stats["inserted"], updated=stats.get("updated", 0),
            deleted=stats.get("deleted", 0), skipped=stats["skipped"],
            errors=stats["errors"], duration=duration,
            status="success" if stats["errors"] == 0 else "partial",
        )
        logger.info(f"✅ Stations import: {stats}")
        return stats

    # ── metadata imports ──────────────────────────────────────────────────

    def import_providers(self, providers: List[Dict], full_import: bool = False) -> Dict[str, int]:
        rows = []
        for p in providers:
            pid = _to_int(p.get("provider_id"))
            if pid is None:
                continue
            rows.append((
                pid,
                p.get("name") or None,
                p.get("url") or None,
                p.get("tel") or None,
                bool(p.get("show", True)),
            ))
        return self._upsert_metadata(
            rows,
            "charging_providers",
            "INSERT INTO charging_providers (provider_id, name, url, tel, show) VALUES %s "
            "ON CONFLICT (provider_id) DO UPDATE SET "
            "name=EXCLUDED.name, url=EXCLUDED.url, tel=EXCLUDED.tel, show=EXCLUDED.show",
        )

    def import_manufacturers(self, manufacturers: List[Dict], full_import: bool = False) -> Dict[str, int]:
        rows = []
        for m in manufacturers:
            mid = _to_int(m.get("manufacturer_id"))
            if mid is None:
                continue
            rows.append((mid, m.get("name") or None))
        return self._upsert_metadata(
            rows,
            "charging_manufacturers",
            "INSERT INTO charging_manufacturers (manufacturer_id, name) VALUES %s "
            "ON CONFLICT (manufacturer_id) DO UPDATE SET name=EXCLUDED.name",
        )

    def import_charger_types(self, charger_types: List[Dict], full_import: bool = False) -> Dict[str, int]:
        rows = []
        for ct in charger_types:
            ctid = _to_int(ct.get("charger_type_id"))
            if ctid is None:
                continue
            rows.append((
                ctid,
                ct.get("name") or None,
                bool(ct.get("is_fast", False)),
                ct.get("current_type") or None,
                _to_int(ct.get("order")),
                bool(ct.get("show", True)),
            ))
        return self._upsert_metadata(
            rows,
            "charging_charger_types",
            "INSERT INTO charging_charger_types "
            "(charger_type_id, name, is_fast, current_type, sort_order, show) VALUES %s "
            "ON CONFLICT (charger_type_id) DO UPDATE SET "
            "name=EXCLUDED.name, is_fast=EXCLUDED.is_fast, current_type=EXCLUDED.current_type, "
            "sort_order=EXCLUDED.sort_order, show=EXCLUDED.show",
        )

    def import_payment_methods(self, payment_methods: List[Dict], full_import: bool = False) -> Dict[str, int]:
        rows = []
        for pm in payment_methods:
            pmid = _to_int(pm.get("payment_method_id"))
            if pmid is None:
                continue
            rows.append((
                pmid,
                pm.get("name") or None,
                bool(pm.get("is_free", False)),
                _to_int(pm.get("order")),
            ))
        return self._upsert_metadata(
            rows,
            "charging_payment_methods",
            "INSERT INTO charging_payment_methods "
            "(payment_method_id, name, is_free, sort_order) VALUES %s "
            "ON CONFLICT (payment_method_id) DO UPDATE SET "
            "name=EXCLUDED.name, is_free=EXCLUDED.is_free, sort_order=EXCLUDED.sort_order",
        )

    def _upsert_metadata(self, rows: list, table_name: str, sql: str) -> Dict[str, int]:
        stats: Dict[str, int] = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
        if not rows:
            return stats
        try:
            with self.conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, sql, rows, page_size=200)
                stats["inserted"] = len(rows)
            self.conn.commit()
            logger.info(f"✅ {table_name}: upserted {len(rows)} rows")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"❌ {table_name} upsert failed: {e}")
            stats["errors"] = len(rows)
        return stats

    # ── import_all ────────────────────────────────────────────────────────

    def import_all(
        self,
        data: Dict,
        full_import: bool = False,
        create_indexes: bool = True,  # no-op in PG (indexes already exist)
    ) -> Dict[str, Dict[str, int]]:
        """Import all data (metadata first, then stations)."""
        results: Dict[str, Dict[str, int]] = {}

        if "metadata" in data:
            meta = data["metadata"]
            if "providers" in meta:
                results["providers"] = self.import_providers(meta["providers"], full_import)
            if "manufacturers" in meta:
                results["manufacturers"] = self.import_manufacturers(meta["manufacturers"], full_import)
            if "charger_types" in meta:
                results["charger_types"] = self.import_charger_types(meta["charger_types"], full_import)
            if "payment_methods" in meta:
                results["payment_methods"] = self.import_payment_methods(meta["payment_methods"], full_import)

        if "stations" in data:
            results["stations"] = self.import_stations(data["stations"], full_import)

        return results

    # ── stats & misc ──────────────────────────────────────────────────────

    def create_indexes(self) -> None:
        """No-op: PostgreSQL indexes created via DDL at table creation time."""
        logger.info("ℹ️ PostgreSQL indexes already exist from DDL — no action needed")

    def get_collection_stats(self) -> Dict:
        tables = [
            "charging_stations", "charging_providers",
            "charging_manufacturers", "charging_charger_types",
            "charging_payment_methods",
        ]
        stats: Dict[str, int] = {}
        try:
            with self.conn.cursor() as cur:
                for t in tables:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    stats[t.replace("charging_", "")] = cur.fetchone()[0]
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
        return stats


# Backward-compat alias — main.py uses ChargingStationMongoDBImporter
ChargingStationMongoDBImporter = ChargingStationPostgresImporter


# ── convenience function ──────────────────────────────────────────────────────

def import_charging_station_data(
    data: Dict,
    full_import: bool = False,
    create_indexes: bool = True,
) -> Dict[str, Dict[str, int]]:
    """Import charging station data to PostgreSQL."""
    importer = ChargingStationPostgresImporter()
    try:
        if not importer.test_connection():
            raise RuntimeError("Failed to connect to PostgreSQL")
        results = importer.import_all(data, full_import, create_indexes=create_indexes)
        logger.info(f"📊 Stats: {importer.get_collection_stats()}")
        return results
    finally:
        importer.close_connection()
