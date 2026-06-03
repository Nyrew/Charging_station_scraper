"""
Rebuilds merged_charging_stations after scraping.
PostgreSQL replacement for update_merged_charging_stations.py.

Logic:
  1. DELETE FROM merged_charging_stations
  2. INSERT INTO merged_charging_stations from charging_stations + id_map
  3. Apply user_changes patches (field-level timestamp wins; skipped if table empty)
"""

import sys
import os
import logging
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import Config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_merged_charging_stations(conn=None) -> None:
    """
    Rebuild merged_charging_stations from charging_stations + user_changes.
    Accepts an optional existing psycopg2 connection; otherwise opens its own.
    """
    own_conn = conn is None
    if own_conn:
        url = Config.get_database_url()
        if not url:
            raise ValueError("DATABASE_URL is not set")
        conn = psycopg2.connect(url)
        conn.autocommit = False

    logger.info("🔄 Rebuilding merged_charging_stations...")

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # STEP 1: clear
            cur.execute("DELETE FROM merged_charging_stations")
            deleted = cur.rowcount
            logger.info(f"🗑️ Deleted {deleted} merged rows")

            # STEP 2: load all raw stations
            cur.execute(
                """
                SELECT
                    cs.station_id,
                    im.internal_id,
                    cs.name,
                    cs.fast_charging,
                    cs.opening_hours_string,
                    cs.charging_slots,
                    cs.fast_charging_slots,
                    cs.parking_slots,
                    cs.station_service,
                    cs.refreshment_venues,
                    cs.is_non_stop,
                    cs.note,
                    cs.date_changed,
                    cs.lat,
                    cs.lon,
                    cs.address,
                    cs.providers,
                    cs.chargers
                FROM charging_stations cs
                LEFT JOIN id_map im
                    ON im.source = 'scrape_charging'
                    AND im.source_id = cs.station_id
                ORDER BY cs.station_id
                """
            )
            stations = cur.fetchall()
            total = len(stations)
            logger.info(f"📊 {total} charging stations to merge")

            now = datetime.utcnow()
            created = 0

            for row in stations:
                row = dict(row)
                station_id = row["station_id"]

                # Apply user_changes if any exist for this station
                row = _apply_user_changes(cur, row, row.get("internal_id"))

                try:
                    cur.execute(
                        """
                        INSERT INTO merged_charging_stations (
                            station_id, internal_id, name, fast_charging,
                            opening_hours_string, charging_slots, fast_charging_slots,
                            parking_slots, station_service, refreshment_venues,
                            is_non_stop, note, date_changed, lat, lon, address,
                            providers, chargers, scraped_chargers,
                            chargers_source, name_source, note_source,
                            last_merged, last_scraped_update
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (station_id) DO NOTHING
                        """,
                        (
                            station_id,
                            row.get("internal_id"),
                            row.get("name"),
                            row.get("fast_charging"),
                            row.get("opening_hours_string"),
                            row.get("charging_slots"),
                            row.get("fast_charging_slots"),
                            row.get("parking_slots"),
                            row.get("station_service"),
                            row.get("refreshment_venues"),
                            row.get("is_non_stop"),
                            row.get("note"),
                            row.get("date_changed"),
                            row.get("lat"),
                            row.get("lon"),
                            row.get("address"),
                            row.get("providers"),   # INTEGER[] — psycopg2 handles list→array
                            psycopg2.extras.Json(row["chargers"]) if row.get("chargers") is not None else None,
                            psycopg2.extras.Json(row["chargers"]) if row.get("chargers") is not None else None,
                            "scrape",
                            "scrape",
                            "scrape",
                            now,
                            now,
                        ),
                    )
                    created += 1
                except Exception as e:
                    logger.error(f"❌ Error inserting merged station {station_id}: {e}")

        conn.commit()
        logger.info(f"✅ Merged rebuild: {created}/{total} stations")

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Merged rebuild failed: {e}")
        raise
    finally:
        if own_conn:
            conn.close()


def _apply_user_changes(cur, row: dict, internal_id: Optional[int]) -> dict:
    """Apply user_changes patches (oldest first). Returns a modified copy of row."""
    if internal_id is None:
        return row

    cur.execute(
        """
        SELECT patch, timestamp
        FROM user_changes
        WHERE internal_id = %s AND target = 'charger'
        ORDER BY timestamp ASC
        """,
        (internal_id,),
    )
    changes = cur.fetchall()
    if not changes:
        return row

    merged = dict(row)

    for change in changes:
        patch = change["patch"] if isinstance(change["patch"], dict) else {}

        # Station-level fields
        station_patch = patch.get("station") or patch
        for field, value in station_patch.items():
            if field.endswith("_timestamp"):
                continue
            if field in ("chargers", "cables", "providers"):
                continue
            if field in merged and value is not None:
                merged[field] = value

        # Chargers array
        chargers_patch = patch.get("chargers")
        if chargers_patch is not None:
            merged["chargers"] = chargers_patch

        # Providers array
        providers_patch = patch.get("providers")
        if providers_patch is not None:
            merged["providers"] = providers_patch

    return merged


if __name__ == "__main__":
    update_merged_charging_stations()
    logger.info("✅ Done")
