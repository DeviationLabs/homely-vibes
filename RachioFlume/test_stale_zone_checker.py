"""Tests for the stale-zone checker."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.stale_zone_checker import StaleZoneChecker, _LAST_RUN_KEY


@pytest.fixture
def tmp_db() -> Iterator[WaterTrackingDB]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        yield WaterTrackingDB(path)
    finally:
        Path(path).unlink(missing_ok=True)


def _seed_controller_zone(
    db: WaterTrackingDB, zone_number: int, name: str, enabled: bool = True
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO zones (id, zone_number, name, enabled) VALUES (?, ?, ?, ?)",
            (f"z{zone_number}", zone_number, name, 1 if enabled else 0),
        )
        conn.commit()


def _seed_zone_session(db: WaterTrackingDB, zone_number: int, start: datetime) -> None:
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO zone_sessions
               (zone_name, zone_number, start_time, end_time, duration_seconds)
               VALUES (?, ?, ?, ?, ?)""",
            (f"Z{zone_number}", zone_number, start, start + timedelta(minutes=10), 600),
        )
        conn.commit()


def _seed_valve(db: WaterTrackingDB, valve_id: str, valve_name: str, base_label: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO hose_valves
               (id, base_station_id, base_station_label, name,
                default_runtime_seconds, detect_flow, battery_status, connected)
               VALUES (?, 'bs1', ?, ?, 600, 1, 'GOOD', 1)""",
            (valve_id, base_label, valve_name),
        )
        conn.commit()


def _seed_hose_session(
    db: WaterTrackingDB, valve_id: str, valve_name: str, base_label: str, start: datetime
) -> None:
    with db.get_connection() as conn:
        conn.execute(
            """INSERT INTO hose_zone_sessions
               (valve_id, base_station_id, valve_name, base_station_label,
                start_time, end_time, duration_seconds)
               VALUES (?, 'bs1', ?, ?, ?, ?, ?)""",
            (
                valve_id,
                valve_name,
                base_label,
                start,
                start + timedelta(minutes=10),
                600,
            ),
        )
        conn.commit()


class TestStaleZoneChecker:
    def test_fresh_zone_no_alert(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        _seed_controller_zone(tmp_db, 1, "Z1")
        _seed_zone_session(tmp_db, 1, now - timedelta(days=2))  # fresh
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        results = checker.evaluate(now=now)
        assert len(results) == 0
        pushover.send_message.assert_not_called()

    def test_stale_controller_zone_alerts(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        _seed_controller_zone(tmp_db, 1, "Z1 FS - Sergio Outer")
        _seed_zone_session(tmp_db, 1, now - timedelta(days=10))  # stale
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        results = checker.evaluate(now=now)
        assert len(results) == 1
        assert results[0]["notified"] is True
        pushover.send_message.assert_called_once()
        call = pushover.send_message.call_args
        assert "Stale Zone" in call[1]["title"]
        assert call[1]["priority"] == -1
        body = call[0][0]
        assert "Z1 FS - Sergio Outer" in body
        assert "7+ days" in body

    def test_never_run_zone_alerts(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        _seed_controller_zone(tmp_db, 9, "Z9 FD - Garage")
        # No session ever
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        results = checker.evaluate(now=now)
        assert results[0]["notified"] is True
        body = pushover.send_message.call_args[0][0]
        assert "never" in body.lower()

    def test_disabled_zone_skipped(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        _seed_controller_zone(tmp_db, 13, "Zone 13", enabled=False)
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        results = checker.evaluate(now=now)
        assert len(results) == 0

    def test_stale_hose_valve_alerts(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        _seed_valve(tmp_db, "v1", "Upper Deck Planters", "Hose Drip Jasmine")
        _seed_hose_session(
            tmp_db, "v1", "Upper Deck Planters", "Hose Drip Jasmine", now - timedelta(days=14)
        )
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        results = checker.evaluate(now=now)
        assert any(r["source"] == "hose" and r["notified"] for r in results)
        body = pushover.send_message.call_args[0][0]
        assert "Upper Deck Planters" in body
        assert "@ Hose Drip Jasmine" in body

    def test_daily_dedup_blocks_second_notification(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        _seed_controller_zone(tmp_db, 1, "Z1")
        # Stale by 10 days
        _seed_zone_session(tmp_db, 1, now - timedelta(days=10))
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        checker.evaluate(now=now)
        pushover.send_message.assert_called_once()
        # Second call same day - dedup
        checker.evaluate(now=now + timedelta(hours=3))
        pushover.send_message.assert_called_once()  # still 1
        # Next day - alert again
        checker.evaluate(now=now + timedelta(days=1))
        assert pushover.send_message.call_count == 2

    def test_maybe_evaluate_hourly_gate(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        # First call runs
        assert checker.maybe_evaluate(now=now) is True
        assert tmp_db.get_metadata(_LAST_RUN_KEY) is not None
        # Call 30 min later — gated, doesn't run
        assert checker.maybe_evaluate(now=now + timedelta(minutes=30)) is False
        # Call 65 min later — runs again
        assert checker.maybe_evaluate(now=now + timedelta(minutes=65)) is True

    def test_dry_run_does_not_send_or_persist(self, tmp_db: WaterTrackingDB) -> None:
        now = datetime(2026, 6, 28, 8, 0, 0)
        _seed_controller_zone(tmp_db, 1, "Z1")
        _seed_zone_session(tmp_db, 1, now - timedelta(days=10))
        pushover = MagicMock()
        checker = StaleZoneChecker(tmp_db, pushover, stale_zone_days=7)
        checker.maybe_evaluate(now=now, dry_run=True)
        pushover.send_message.assert_not_called()
        assert tmp_db.get_metadata(_LAST_RUN_KEY) is None
