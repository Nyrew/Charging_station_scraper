"""
PostgreSQL ID map manager — replaces id_map_manager.py.
Maps (source, source_id) → internal_id using the id_map table.
"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PostgresIdMapManager:
    """Manages the id_map table in PostgreSQL."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def get_or_create_internal_id(self, source: str, source_id: int) -> int:
        """
        Return existing internal_id or insert a new mapping row.
        Uses MAX(internal_id)+1 as next value — safe for sequential scraper runs.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT internal_id FROM id_map WHERE source = %s AND source_id = %s",
                (source, source_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE id_map SET last_seen = NOW() WHERE source = %s AND source_id = %s",
                    (source, source_id),
                )
                return row[0]

            cur.execute(
                """
                INSERT INTO id_map (internal_id, source, source_id, first_seen, last_seen)
                SELECT COALESCE(MAX(internal_id), 0) + 1, %s, %s, NOW(), NOW()
                FROM id_map
                ON CONFLICT (source, source_id) DO UPDATE SET last_seen = NOW()
                RETURNING internal_id
                """,
                (source, source_id),
            )
            internal_id = cur.fetchone()[0]
            logger.debug(f"Created id_map entry: source={source} source_id={source_id} → internal_id={internal_id}")
            return internal_id

    def get_internal_id(self, source: str, source_id: int) -> Optional[int]:
        """Return internal_id for a known mapping, or None if not found."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT internal_id FROM id_map WHERE source = %s AND source_id = %s",
                (source, source_id),
            )
            row = cur.fetchone()
            return row[0] if row else None
