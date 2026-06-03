"""
PostgreSQL import logger — replaces import_logger.py.
Logs operations to the info_import table (fails silently if table doesn't exist).
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional
import logging

import psycopg2

logger = logging.getLogger(__name__)


class PostgresImportLogger:
    """Logs import operations to info_import table."""

    def __init__(self, conn) -> None:
        self.conn = conn
        self._table_exists: Optional[bool] = None

    def _check_table(self) -> bool:
        if self._table_exists is not None:
            return self._table_exists
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'info_import' AND table_schema = 'public'"
                )
                self._table_exists = cur.fetchone() is not None
        except Exception:
            self._table_exists = False
        return self._table_exists

    def log_import(
        self,
        collection_name: str,
        operation_type: str,
        inserted: int = 0,
        updated: int = 0,
        deleted: int = 0,
        skipped: int = 0,
        errors: int = 0,
        duration: Optional[float] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        additional_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log an import operation. Silently skips if info_import table doesn't exist."""
        if not self._check_table():
            return

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO info_import
                        (collection_name, operation_type, inserted, updated, deleted,
                         skipped, errors, timestamp, duration_seconds, status,
                         error_message, additional_info)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        collection_name,
                        operation_type,
                        inserted,
                        updated,
                        -deleted if deleted > 0 else 0,
                        skipped,
                        errors,
                        datetime.utcnow(),
                        duration,
                        status,
                        error_message,
                        json.dumps(additional_info or {}),
                    ),
                )
            logger.debug(
                f"📝 Logged {operation_type} on {collection_name}: "
                f"+{inserted} ~{updated} -{deleted} ⊘{skipped} ✗{errors}"
            )
        except psycopg2.Error as e:
            logger.warning(f"⚠️ Could not log import operation: {e}")
