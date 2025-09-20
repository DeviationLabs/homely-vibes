"""Data storage for water tracking integration."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import contextmanager

from rachio_client import WateringEvent, Zone
from flume_client import WaterReading
from lib.logger import get_logger


class WaterTrackingDB:
    """SQLite database for storing water tracking data."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.logger = get_logger(__name__)
        self.logger.info(f"Initializing water tracking database at {self.db_path}")
        self.init_database()

    def init_database(self) -> None:
        """Create database tables if they don't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Zones table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS zones (
                    id TEXT PRIMARY KEY,
                    zone_number INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Watering events table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS watering_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_date TIMESTAMP NOT NULL,
                    zone_name TEXT NOT NULL,
                    zone_number INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    duration_seconds INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Water readings table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS water_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT DEFAULT 'GAL',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Zone sessions table (computed from events)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS zone_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zone_name TEXT NOT NULL,
                    zone_number INTEGER NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    duration_seconds INTEGER,
                    total_water_used REAL DEFAULT 0.0,
                    average_flow_rate REAL DEFAULT 0.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Collection metadata table (for tracking last collection timestamps)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS collection_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Create indexes for better query performance
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_watering_events_date ON watering_events(event_date)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_watering_events_zone ON watering_events(zone_number)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_water_readings_timestamp ON water_readings(timestamp)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_zone_sessions_times ON zone_sessions(start_time, end_time)"
            )

            conn.commit()

    @contextmanager
    def get_connection(self):
        """Get database connection with automatic cleanup."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access to rows
        try:
            yield conn
        finally:
            conn.close()

    def save_zones(self, zones: List[Zone]) -> None:
        """Save or update zones in database."""
        self.logger.info(f"Saving {len(zones)} zones to database")
        with self.get_connection() as conn:
            cursor = conn.cursor()

            for zone in zones:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO zones (id, zone_number, name, enabled, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        zone.id,
                        zone.zone_number,
                        zone.name,
                        zone.enabled,
                        datetime.now(),
                    ),
                )

            conn.commit()
            self.logger.debug(f"Successfully saved {len(zones)} zones")

    def save_watering_events(self, events: List[WateringEvent]) -> None:
        """Save watering events to database."""
        if not events:
            self.logger.debug("No watering events to save")
            return

        self.logger.info(f"Saving {len(events)} watering events to database")
        with self.get_connection() as conn:
            cursor = conn.cursor()

            for event in events:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO watering_events 
                    (event_date, zone_name, zone_number, event_type, duration_seconds)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        event.event_date,
                        event.zone_name,
                        event.zone_number,
                        event.event_type,
                        event.duration_seconds,
                    ),
                )

            conn.commit()

    def save_water_readings(self, readings: List[WaterReading]) -> None:
        """Save water readings to database."""
        if not readings:
            self.logger.debug("No water readings to save")
            return

        self.logger.info(f"Saving {len(readings)} water readings to database")
        with self.get_connection() as conn:
            cursor = conn.cursor()

            for reading in readings:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO water_readings (timestamp, value, unit)
                    VALUES (?, ?, ?)
                """,
                    (reading.timestamp, reading.value, reading.unit),
                )

            conn.commit()

    def get_zone_sessions(
        self, start_date: datetime, end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Get zone watering sessions for a date range."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT * FROM zone_sessions 
                WHERE start_time >= ? AND start_time <= ?
                ORDER BY start_time
            """,
                (start_date, end_date),
            )

            return [dict(row) for row in cursor.fetchall()]

    def compute_zone_sessions(self) -> None:
        """Compute zone sessions from watering events."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Clear existing sessions
            cursor.execute("DELETE FROM zone_sessions")

            # Get all zone start events
            cursor.execute(
                """
                SELECT * FROM watering_events 
                WHERE event_type = 'ZONE_STARTED'
                ORDER BY zone_number, event_date
            """
            )

            start_events = cursor.fetchall()

            for start_event in start_events:
                # Find corresponding end event
                cursor.execute(
                    """
                    SELECT * FROM watering_events 
                    WHERE zone_number = ? 
                    AND event_type IN ('ZONE_COMPLETED', 'ZONE_STOPPED')
                    AND event_date > ?
                    ORDER BY event_date
                    LIMIT 1
                """,
                    (start_event["zone_number"], start_event["event_date"]),
                )

                end_event = cursor.fetchone()

                if end_event:
                    # Calculate session duration
                    start_time = datetime.fromisoformat(start_event["event_date"])
                    end_time = datetime.fromisoformat(end_event["event_date"])
                    duration = int((end_time - start_time).total_seconds())

                    # Get water usage during this session
                    water_used = self._get_water_usage_for_period(start_time, end_time)

                    # Calculate average flow rate
                    avg_flow_rate = (
                        (water_used / (duration / 60)) if duration > 0 else 0.0
                    )

                    # Insert session
                    cursor.execute(
                        """
                        INSERT INTO zone_sessions 
                        (zone_name, zone_number, start_time, end_time, duration_seconds, 
                         total_water_used, average_flow_rate)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            start_event["zone_name"],
                            start_event["zone_number"],
                            start_time,
                            end_time,
                            duration,
                            water_used,
                            avg_flow_rate,
                        ),
                    )

            conn.commit()

    def _get_water_usage_for_period(
        self, start_time: datetime, end_time: datetime
    ) -> float:
        """Get total water usage for a time period."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT SUM(value) as total FROM water_readings
                WHERE timestamp >= ? AND timestamp <= ?
            """,
                (start_time, end_time),
            )

            result = cursor.fetchone()
            return result["total"] or 0.0

    def get_weekly_zone_stats(self, start_date: datetime) -> List[Dict[str, Any]]:
        """Get weekly statistics by zone."""
        end_date = start_date + timedelta(days=7)

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT 
                    zone_name,
                    zone_number,
                    COUNT(*) as session_count,
                    SUM(duration_seconds) as total_duration_seconds,
                    AVG(duration_seconds) as avg_duration_seconds,
                    SUM(total_water_used) as total_water_used,
                    AVG(average_flow_rate) as avg_flow_rate
                FROM zone_sessions
                WHERE start_time >= ? AND start_time < ?
                GROUP BY zone_name, zone_number
                ORDER BY zone_number
            """,
                (start_date, end_date),
            )

            return [dict(row) for row in cursor.fetchall()]

    def get_period_zone_stats(
        self, start_date: datetime, end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Get period statistics by zone for a custom date range."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT 
                    zone_name,
                    zone_number,
                    COUNT(*) as session_count,
                    SUM(duration_seconds) as total_duration_seconds,
                    AVG(duration_seconds) as avg_duration_seconds,
                    SUM(total_water_used) as total_water_used,
                    AVG(average_flow_rate) as avg_flow_rate
                FROM zone_sessions
                WHERE start_time >= ? AND start_time < ?
                GROUP BY zone_name, zone_number
                ORDER BY zone_number
            """,
                (start_date, end_date),
            )

            return [dict(row) for row in cursor.fetchall()]

    def get_raw_data_intervals(
        self, start_time: datetime, end_time: datetime, interval_minutes: int = 5
    ) -> List[Dict[str, Any]]:
        """Get raw data aggregated into time intervals."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create intervals by rounding timestamps to the specified interval
            cursor.execute(
                """
                SELECT 
                    datetime(
                        (strftime('%s', timestamp) / (? * 60)) * (? * 60),
                        'unixepoch'
                    ) as interval_start,
                    AVG(flow_rate) as avg_flow_rate,
                    MAX(flow_rate) as max_flow_rate,
                    MIN(flow_rate) as min_flow_rate,
                    COUNT(*) as data_points,
                    AVG(CASE WHEN flow_rate > 0.1 THEN flow_rate END) as avg_active_flow_rate
                FROM flume_readings
                WHERE timestamp >= ? AND timestamp <= ?
                GROUP BY interval_start
                ORDER BY interval_start
            """,
                (interval_minutes, interval_minutes, start_time, end_time),
            )

            return [dict(row) for row in cursor.fetchall()]

    def get_last_collection_timestamp(self, source: str) -> Optional[datetime]:
        """Get the last collection timestamp for a source (rachio or flume)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM collection_metadata WHERE key = ?",
                (f"last_{source}_collection",),
            )
            result = cursor.fetchone()
            if result:
                return datetime.fromisoformat(result["value"])
            return None

    def set_last_collection_timestamp(self, source: str, timestamp: datetime) -> None:
        """Set the last collection timestamp for a source."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO collection_metadata (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
                (f"last_{source}_collection", timestamp.isoformat()),
            )
            conn.commit()

    def get_last_data_timestamp(self, source: str) -> Optional[datetime]:
        """Get the actual last timestamp from data tables."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if source == "rachio":
                cursor.execute(
                    "SELECT MAX(event_date) as last_timestamp FROM watering_events"
                )
            elif source == "flume":
                cursor.execute(
                    "SELECT MAX(timestamp) as last_timestamp FROM water_readings"
                )
            else:
                raise ValueError(f"Unknown source: {source}")

            result = cursor.fetchone()
            if result and result["last_timestamp"]:
                return datetime.fromisoformat(result["last_timestamp"])
            return None
