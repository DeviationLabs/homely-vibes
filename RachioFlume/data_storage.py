"""Data storage for water tracking integration."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Generator
from contextlib import contextmanager

from RachioFlume.rachio_client import WateringEvent, Zone
from RachioFlume.flume_client import WaterReading
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

            # === Hose-timer tables (Rachio Smart Hose Timer / cloud-rest.rach.io) ===
            # Kept in separate tables from the controller schema so multiple
            # Bluetooth valves under one or more base stations can coexist
            # without zone_number collisions or schema migrations.
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS hose_valves (
                    id TEXT PRIMARY KEY,                    -- valveId
                    base_station_id TEXT NOT NULL,
                    base_station_label TEXT NOT NULL,       -- human label (e.g. "Hose Drip Jasmine")
                    name TEXT NOT NULL,                     -- valve name (e.g. "Upper Deck Planters")
                    default_runtime_seconds INTEGER,
                    detect_flow BOOLEAN DEFAULT 0,
                    battery_status TEXT,
                    connected BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS hose_watering_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    valve_id TEXT NOT NULL,
                    base_station_id TEXT NOT NULL,
                    event_date TIMESTAMP NOT NULL,          -- run start time
                    event_type TEXT NOT NULL,               -- ZONE_STARTED | ZONE_COMPLETED
                    duration_seconds INTEGER,               -- planned (start) or actual (complete)
                    reason TEXT,                            -- QUICK_RUN | SCHEDULE | etc.
                    flow_detected INTEGER,                  -- 0/1, NULL if not reported
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(valve_id, event_date, event_type)
                )
            """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS hose_zone_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    valve_id TEXT NOT NULL,
                    base_station_id TEXT NOT NULL,
                    valve_name TEXT NOT NULL,
                    base_station_label TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    duration_seconds INTEGER,
                    flow_detected INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(valve_id, start_time)
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
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_hose_events_valve ON hose_watering_events(valve_id, event_date)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_hose_sessions_times ON hose_zone_sessions(start_time, end_time)"
            )

            conn.commit()

        # One-shot dedup of legacy per-device rows in water_readings.
        # Pre-2026-06-28, the Flume collector saved one row per (timestamp,
        # device), so each minute had two rows: the real meter value and a
        # 0.0 from the bridge. Dedup by keeping MAX value per timestamp —
        # since the bridge always read 0, MAX preserves the meter's reading
        # for every minute that ever had real flow.
        self._dedup_water_readings()

    def _dedup_water_readings(self) -> None:
        """Collapse duplicate-per-timestamp rows in water_readings (one-shot)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) - COUNT(DISTINCT timestamp) AS dupes FROM water_readings"
            )
            row = cursor.fetchone()
            dupes = (row["dupes"] if row else 0) or 0
            if dupes == 0:
                return
            self.logger.info(f"Deduping {dupes} legacy duplicate-per-timestamp water_readings rows")
            cursor.executescript(
                """
                CREATE TABLE water_readings_new AS
                SELECT MIN(id) AS id, timestamp, MAX(value) AS value,
                       MAX(unit) AS unit, MAX(created_at) AS created_at
                FROM water_readings
                GROUP BY timestamp;
                DROP TABLE water_readings;
                ALTER TABLE water_readings_new RENAME TO water_readings;
                CREATE INDEX IF NOT EXISTS idx_water_readings_timestamp
                    ON water_readings(timestamp);
                """
            )
            conn.commit()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
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

    def get_zone_sessions(self, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
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
                    avg_flow_rate = (water_used / (duration / 60)) if duration > 0 else 0.0

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

    def _get_water_usage_for_period(self, start_time: datetime, end_time: datetime) -> float:
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
        self,
        start_time: datetime,
        end_time: datetime,
        interval_minutes: int = 5,
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

    def get_metadata(self, key: str) -> Optional[str]:
        """Get a raw value from collection_metadata, or None if missing."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM collection_metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        """Upsert a value into collection_metadata."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO collection_metadata (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """,
                (key, value),
            )
            conn.commit()

    def delete_metadata(self, key: str) -> None:
        """Remove a metadata key (no-op if missing)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM collection_metadata WHERE key = ?", (key,))
            conn.commit()

    # =====================================================================
    # Hose-timer storage (separate from controller schema)
    # =====================================================================

    def save_hose_valves(self, valves: List[Dict[str, Any]]) -> None:
        """Upsert hose-timer valves (one row per (base_station, valve))."""
        if not valves:
            return
        self.logger.info(f"Saving {len(valves)} hose-timer valves")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for v in valves:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO hose_valves (
                        id, base_station_id, base_station_label, name,
                        default_runtime_seconds, detect_flow, battery_status,
                        connected, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        v["id"],
                        v["base_station_id"],
                        v["base_station_label"],
                        v["name"],
                        v.get("default_runtime_seconds"),
                        1 if v.get("detect_flow") else 0,
                        v.get("battery_status"),
                        1 if v.get("connected", True) else 0,
                        datetime.now(),
                    ),
                )
            conn.commit()

    def save_hose_watering_event(self, event: Dict[str, Any]) -> None:
        """Insert a hose-timer event (idempotent on (valve_id, event_date, event_type))."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO hose_watering_events (
                    valve_id, base_station_id, event_date, event_type,
                    duration_seconds, reason, flow_detected
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["valve_id"],
                    event["base_station_id"],
                    event["event_date"],
                    event["event_type"],
                    event.get("duration_seconds"),
                    event.get("reason"),
                    None
                    if event.get("flow_detected") is None
                    else (1 if event["flow_detected"] else 0),
                ),
            )
            conn.commit()

    def save_hose_zone_session(self, session: Dict[str, Any]) -> None:
        """Insert a finalized hose-timer session row."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO hose_zone_sessions (
                    valve_id, base_station_id, valve_name, base_station_label,
                    start_time, end_time, duration_seconds, flow_detected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["valve_id"],
                    session["base_station_id"],
                    session["valve_name"],
                    session["base_station_label"],
                    session["start_time"],
                    session["end_time"],
                    session["duration_seconds"],
                    None
                    if session.get("flow_detected") is None
                    else (1 if session["flow_detected"] else 0),
                ),
            )
            conn.commit()

    def get_hose_zone_sessions(
        self, start_date: datetime, end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Get hose-timer sessions for a date range."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM hose_zone_sessions
                WHERE start_time >= ? AND start_time <= ?
                ORDER BY start_time
                """,
                (start_date, end_date),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_last_data_timestamp(self, source: str) -> Optional[datetime]:
        """Get the actual last timestamp from data tables."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if source == "rachio":
                cursor.execute("SELECT MAX(event_date) as last_timestamp FROM watering_events")
            elif source == "flume":
                cursor.execute("SELECT MAX(timestamp) as last_timestamp FROM water_readings")
            else:
                raise ValueError(f"Unknown source: {source}")

            result = cursor.fetchone()
            if result and result["last_timestamp"]:
                return datetime.fromisoformat(result["last_timestamp"])
            return None
