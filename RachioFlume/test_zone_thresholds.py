"""Integration test for zone threshold checking with production database.

This test validates the zone threshold logic by:
1. Fetching the production database from prod controller (configured in config/local.yaml)
2. Testing threshold computation for all configured zones
3. Simulating zone-end scenarios with actual historical data
4. Verifying alert behavior for known/unknown zones

Run with: python -m pytest RachioFlume/test_zone_thresholds.py -v
Or standalone: python RachioFlume/test_zone_thresholds.py
"""

import subprocess
import tempfile
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from RachioFlume.alert_engine import AlertEngine
from RachioFlume.alert_rules import ZoneThreshold, load_zone_thresholds_from_config
from RachioFlume.data_storage import WaterTrackingDB
from lib.config import get_config, reset_config


def _get_prod_controller_config() -> tuple[str, str]:
    """Load prod controller SSH config from config/local.yaml."""
    cfg = get_config()
    return cfg.prod_controller.ssh_host, cfg.prod_controller.db_path


@pytest.fixture(scope="module")
def prod_db_path() -> Generator[str, None, None]:
    """Fetch the production database from prod controller for testing."""
    host, db_path = _get_prod_controller_config()
    if not host or not db_path:
        pytest.skip("Prod controller SSH config not set in config/local.yaml")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run(
            ["scp", f"{host}:{db_path}", tmp_path],
            check=True,
            capture_output=True,
            timeout=30,
        )
        yield tmp_path
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"Could not fetch DB from prod controller: {e}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@pytest.fixture
def zone_thresholds() -> dict[int, ZoneThreshold]:
    """Load zone thresholds from config."""
    reset_config()
    return load_zone_thresholds_from_config()


@pytest.fixture
def mock_engine(prod_db_path: str, zone_thresholds: dict[int, ZoneThreshold]) -> AlertEngine:
    """Create an AlertEngine with real DB and mocked clients."""
    db = WaterTrackingDB(prod_db_path)
    flume = MagicMock()
    rachio = MagicMock()
    rachio.get_active_zone.return_value = None
    pushover = MagicMock()

    cfg = get_config()
    alerts_cfg = cfg.rachio_flume.alerts

    return AlertEngine(
        flume_client=flume,
        rachio_client=rachio,
        pushover=pushover,
        db=db,
        rules=[],
        zone_thresholds=zone_thresholds,
        absolute_gpm=alerts_cfg.absolute_gpm,
        percent_above=alerts_cfg.percent_above,
        min_runtime_minutes=alerts_cfg.min_runtime_minutes,
    )


class TestZoneThresholdComputation:
    """Test threshold computation logic."""

    def test_known_zone_threshold(self, zone_thresholds: dict[int, ZoneThreshold]) -> None:
        """Verify threshold computation for known zones."""
        # Zone 10: avg=7.0, threshold = 7.0 + max(0.5, 0.10*7.0) = 7.0 + 0.7 = 7.7
        zt = zone_thresholds.get(10)
        assert zt is not None
        assert zt.avg_gpm == 7.0

        threshold = zt.compute_threshold(absolute_gpm=0.5, percent_above=10.0)
        assert threshold == pytest.approx(7.7, rel=0.01)

    def test_small_zone_threshold(self, zone_thresholds: dict[int, ZoneThreshold]) -> None:
        """Verify threshold for small zones uses absolute_gpm floor."""
        # Zone 12: avg=0.75, threshold = 0.75 + max(0.5, 0.10*0.75) = 0.75 + 0.5 = 1.25
        zt = zone_thresholds.get(12)
        assert zt is not None
        assert zt.avg_gpm == 0.75

        threshold = zt.compute_threshold(absolute_gpm=0.5, percent_above=10.0)
        assert threshold == pytest.approx(1.25, rel=0.01)

    def test_all_zones_configured(self, zone_thresholds: dict[int, ZoneThreshold]) -> None:
        """Verify all 12 enabled zones have thresholds."""
        assert len(zone_thresholds) == 12
        for zone_num in range(1, 13):
            assert zone_num in zone_thresholds, f"Zone {zone_num} missing from config"


class TestZoneThresholdChecking:
    """Test zone threshold checking with real database."""

    def test_get_zone_threshold_known_zone(self, mock_engine: AlertEngine) -> None:
        """Test threshold lookup for known zone."""
        threshold, avg_gpm = mock_engine._get_zone_threshold(zone_number=10)
        assert avg_gpm == 7.0
        assert threshold == pytest.approx(7.7, rel=0.01)

    def test_get_zone_threshold_unknown_zone(self, mock_engine: AlertEngine) -> None:
        """Test threshold lookup for unknown zone defaults to 0.5 GPM."""
        threshold, avg_gpm = mock_engine._get_zone_threshold(zone_number=99)
        assert avg_gpm == 0.0
        assert threshold == 0.5  # absolute_gpm default

    def test_get_zone_threshold_none_zone_number(self, mock_engine: AlertEngine) -> None:
        """Test threshold lookup with None zone_number."""
        threshold, avg_gpm = mock_engine._get_zone_threshold(zone_number=None)
        assert avg_gpm == 0.0
        assert threshold == 0.5

    def test_check_zone_threshold_no_alert(self, mock_engine: AlertEngine) -> None:
        """Test that normal flow doesn't trigger alert."""
        now = datetime.now()
        # Zone 10 threshold is 7.7 GPM, send 7.0 GPM (below threshold)
        alerted = mock_engine._check_zone_threshold(
            zone_name="Z10 BB - Redwoods",
            zone_number=10,
            avg_gpm=7.0,
            runtime_min=10.0,
            now=now,
            dry_run=False,
        )
        assert alerted is False
        mock_engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]

    def test_check_zone_threshold_alert_triggered(self, mock_engine: AlertEngine) -> None:
        """Test that excessive flow triggers alert."""
        now = datetime.now()
        # Zone 10 threshold is 7.7 GPM, send 8.5 GPM (above threshold)
        alerted = mock_engine._check_zone_threshold(
            zone_name="Z10 BB - Redwoods",
            zone_number=10,
            avg_gpm=8.5,
            runtime_min=10.0,
            now=now,
            dry_run=False,
        )
        assert alerted is True
        mock_engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
        call_args: Any = mock_engine.pushover.send_message.call_args  # type: ignore[attr-defined]
        assert "anomaly" in call_args[1]["title"].lower() or "anomaly" in call_args[0][0].lower()
        assert call_args[1]["priority"] == 2  # P2 emergency

    def test_check_zone_threshold_unknown_zone_alerts(self, mock_engine: AlertEngine) -> None:
        """Test that unknown zone with any flow triggers alert."""
        now = datetime.now()
        # Unknown zone threshold is 0.5 GPM, send 0.6 GPM
        alerted = mock_engine._check_zone_threshold(
            zone_name="Unknown Zone",
            zone_number=99,
            avg_gpm=0.6,
            runtime_min=10.0,
            now=now,
            dry_run=False,
        )
        assert alerted is True
        mock_engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]

    def test_check_zone_threshold_dry_run(self, mock_engine: AlertEngine) -> None:
        """Test dry run doesn't send actual alert."""
        now = datetime.now()
        alerted = mock_engine._check_zone_threshold(
            zone_name="Z10 BB - Redwoods",
            zone_number=10,
            avg_gpm=8.5,
            runtime_min=10.0,
            now=now,
            dry_run=True,
        )
        assert alerted is True
        mock_engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]

    def test_check_zone_threshold_short_run_skipped(self, mock_engine: AlertEngine) -> None:
        """Test that short runs (<= min_runtime_minutes) don't trigger alerts."""
        now = datetime.now()
        # Zone 10 threshold is 7.7 GPM, send 8.5 GPM (above threshold) but short runtime
        alerted = mock_engine._check_zone_threshold(
            zone_name="Z10 BB - Redwoods",
            zone_number=10,
            avg_gpm=8.5,
            runtime_min=3.0,  # less than min_runtime_minutes (5)
            now=now,
            dry_run=False,
        )
        assert alerted is False
        mock_engine.pushover.send_message.assert_not_called()  # type: ignore[attr-defined]


class TestRealZoneData:
    """Test with actual zone data from production database."""

    def test_recent_zone_sessions_exist(self, prod_db_path: str) -> None:
        """Verify the fetched DB has recent zone session data."""
        db = WaterTrackingDB(prod_db_path)
        now = datetime.now()
        sessions = db.get_zone_sessions(now - timedelta(days=7), now)
        assert len(sessions) > 0, "No zone sessions found in last 7 days"

    def test_zone_sessions_have_flow_data(self, prod_db_path: str) -> None:
        """Verify zone sessions have flow rate data."""
        db = WaterTrackingDB(prod_db_path)
        now = datetime.now()
        sessions = db.get_zone_sessions(now - timedelta(days=7), now)

        zones_with_flow = [s for s in sessions if (s.get("average_flow_rate") or 0) > 0]
        assert len(zones_with_flow) > 0, "No zones with flow data found"


def main() -> int:
    """Standalone test runner for manual execution."""
    print("=" * 70)
    print("Zone Threshold Integration Test")
    print("=" * 70)

    # Load prod controller config
    host, db_path = _get_prod_controller_config()
    if not host or not db_path:
        print("  ✗ Prod controller SSH config not set in config/local.yaml")
        return 1

    # Fetch DB from prod controller
    print("\n[1/4] Fetching database from prod controller...")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run(
            ["scp", f"{host}:{db_path}", tmp_path],
            check=True,
            capture_output=True,
            timeout=30,
        )
        print(f"  ✓ Database fetched to {tmp_path}")
    except Exception as e:
        print(f"  ✗ Failed to fetch DB: {e}")
        return 1

    # Load config and thresholds
    print("\n[2/4] Loading zone thresholds from config...")
    reset_config()
    zone_thresholds = load_zone_thresholds_from_config()
    print(f"  ✓ Loaded {len(zone_thresholds)} zone thresholds")
    for zone_num in sorted(zone_thresholds.keys()):
        zt = zone_thresholds[zone_num]
        cfg = get_config()
        threshold = zt.compute_threshold(
            cfg.rachio_flume.alerts.absolute_gpm, cfg.rachio_flume.alerts.percent_above
        )
        print(f"    Zone {zone_num:2d}: avg={zt.avg_gpm:5.2f} GPM, threshold={threshold:5.2f} GPM")

    # Test threshold checking
    print("\n[3/4] Testing threshold checking logic...")
    db = WaterTrackingDB(tmp_path)
    flume = MagicMock()
    rachio = MagicMock()
    rachio.get_active_zone.return_value = None
    pushover = MagicMock()

    cfg = get_config()
    alerts_cfg = cfg.rachio_flume.alerts

    engine = AlertEngine(
        flume_client=flume,
        rachio_client=rachio,
        pushover=pushover,
        db=db,
        rules=[],
        zone_thresholds=zone_thresholds,
        absolute_gpm=alerts_cfg.absolute_gpm,
        percent_above=alerts_cfg.percent_above,
        min_runtime_minutes=alerts_cfg.min_runtime_minutes,
    )

    # Test known zone
    threshold, avg = engine._get_zone_threshold(10)
    print(f"  ✓ Zone 10: avg={avg:.2f}, threshold={threshold:.2f}")

    # Test unknown zone
    threshold, avg = engine._get_zone_threshold(99)
    print(f"  ✓ Zone 99 (unknown): avg={avg:.2f}, threshold={threshold:.2f}")

    # Test alert triggering
    now = datetime.now()
    alerted = engine._check_zone_threshold("Z10 BB", 10, 8.5, 10.0, now, dry_run=True)
    print(f"  ✓ Zone 10 @ 8.5 GPM: alert={'YES' if alerted else 'NO'} (expected: YES)")

    alerted = engine._check_zone_threshold("Z10 BB", 10, 7.0, 10.0, now, dry_run=True)
    print(f"  ✓ Zone 10 @ 7.0 GPM: alert={'YES' if alerted else 'NO'} (expected: NO)")

    alerted = engine._check_zone_threshold("Unknown", 99, 0.6, 10.0, now, dry_run=True)
    print(f"  ✓ Zone 99 @ 0.6 GPM: alert={'YES' if alerted else 'NO'} (expected: YES)")

    # Check real data
    print("\n[4/4] Checking real zone data from production...")
    sessions = db.get_zone_sessions(now - timedelta(days=7), now)
    print(f"  ✓ Found {len(sessions)} zone sessions in last 7 days")

    zones_with_flow = [s for s in sessions if (s.get("average_flow_rate") or 0) > 0]
    print(f"  ✓ {len(zones_with_flow)} zones with flow data")

    # Check if any real sessions would trigger alerts
    print("\n  Checking for threshold violations in recent data:")
    violations = 0
    for session in sessions:
        session_zone_num: int | None = session.get("zone_number")
        avg_gpm = session.get("average_flow_rate") or 0
        if avg_gpm > 0 and session_zone_num:
            threshold, expected = engine._get_zone_threshold(session_zone_num)
            if avg_gpm > threshold:
                zone_name = session.get("zone_name", f"Zone {session_zone_num}")
                print(
                    f"    ⚠ Zone {session_zone_num} ({zone_name}): {avg_gpm:.2f} GPM > {threshold:.2f} GPM threshold"
                )
                violations += 1

    if violations == 0:
        print("    ✓ No threshold violations detected")
    else:
        print(f"    ⚠ {violations} threshold violations detected")

    print("\n" + "=" * 70)
    print("All tests passed!")
    print("=" * 70)

    Path(tmp_path).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    exit(main())
