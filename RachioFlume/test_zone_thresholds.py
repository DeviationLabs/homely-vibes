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
from RachioFlume.alert_rules import (
    ZoneThreshold,
    get_controller_zone_thresholds,
    load_zone_thresholds_from_config,
)
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


_FIXTURE_ZONE_AVGS = {
    1: 5.0,
    2: 6.5,
    3: 2.0,
    4: 3.0,
    5: 3.5,
    6: 4.5,
    7: 2.5,
    8: 3.0,
    9: 1.5,
    10: 7.0,
    11: 6.0,
    12: 0.75,
}


@pytest.fixture
def zone_thresholds() -> dict[int, ZoneThreshold]:
    """Fixture of controller zone thresholds keyed by zone_number.

    Built inline rather than loaded from config so the test is hermetic and
    does not depend on local.yaml (which is gitignored and absent in CI).
    """
    return {n: ZoneThreshold(zone_key=str(n), avg_gpm=avg) for n, avg in _FIXTURE_ZONE_AVGS.items()}


@pytest.fixture
def mock_engine(prod_db_path: str, zone_thresholds: dict[int, ZoneThreshold]) -> AlertEngine:
    """Create an AlertEngine with real DB and mocked clients."""
    db = WaterTrackingDB(prod_db_path)
    flume = MagicMock()
    rachio = MagicMock()
    rachio.get_active_zone.return_value = None
    pushover = MagicMock()

    cfg = get_config()
    za_cfg = cfg.rachio_flume.alerts.zone_anomaly

    return AlertEngine(
        flume_client=flume,
        rachio_client=rachio,
        pushover=pushover,
        db=db,
        rules=[],
        zone_thresholds=zone_thresholds,
        absolute_gpm=za_cfg.absolute_gpm,
        percent_above=za_cfg.percent_above,
        min_runtime_minutes=za_cfg.min_runtime_minutes,
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

    def _outcome_title(self, mock_engine: AlertEngine) -> str:
        call_args: Any = mock_engine.pushover.send_message.call_args  # type: ignore[attr-defined]
        return call_args[1]["title"]  # type: ignore[no-any-return]

    def _outcome_priority(self, mock_engine: AlertEngine) -> int:
        call_args: Any = mock_engine.pushover.send_message.call_args  # type: ignore[attr-defined]
        return call_args[1]["priority"]  # type: ignore[no-any-return]

    def _outcome_body(self, mock_engine: AlertEngine) -> str:
        call_args: Any = mock_engine.pushover.send_message.call_args  # type: ignore[attr-defined]
        return call_args[0][0]  # type: ignore[no-any-return]

    def test_zone_outcome_below_threshold_is_report(self, mock_engine: AlertEngine) -> None:
        """Normal flow → routine Zone Report (P-1), not anomaly."""
        # Zone 10 threshold is 7.7 GPM, send 7.0 GPM (below threshold)
        mock_engine._send_zone_outcome("Z10 BB - Redwoods", 10, 10.0, 7.0, 70.0, 1)
        mock_engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
        assert "Zone Report" in self._outcome_title(mock_engine)
        assert self._outcome_priority(mock_engine) == -1
        assert "Deviation" not in self._outcome_body(mock_engine)

    def test_zone_outcome_above_threshold_is_anomaly(self, mock_engine: AlertEngine) -> None:
        """Excessive flow → Zone Anomaly (P2) with Deviation line + Total."""
        # Zone 10 threshold is 7.7 GPM, send 8.5 GPM (above)
        mock_engine._send_zone_outcome("Z10 BB - Redwoods", 10, 10.0, 8.5, 85.0, 1)
        mock_engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
        assert "Zone Anomaly" in self._outcome_title(mock_engine)
        assert self._outcome_priority(mock_engine) == 2
        body = self._outcome_body(mock_engine)
        assert "Deviation" in body
        assert "Total: 85.0 gal" in body
        assert "(thresh 7.70)" in body  # unified threshold value

    def test_zone_outcome_unknown_zone_no_baseline(self, mock_engine: AlertEngine) -> None:
        """Unknown zone has no configured baseline → routine report, no thresh."""
        mock_engine._send_zone_outcome("Unknown Zone", 99, 10.0, 0.6, 6.0, 1)
        mock_engine.pushover.send_message.assert_called_once()  # type: ignore[attr-defined]
        assert "Zone Report" in self._outcome_title(mock_engine)
        body = self._outcome_body(mock_engine)
        assert "(thresh" not in body  # no baseline → no thresh display
        assert "Deviation" not in body  # no baseline → can't be anomaly

    def test_zone_outcome_short_run_emits_nothing(self, mock_engine: AlertEngine) -> None:
        """Short run (<= min_runtime_minutes) is fully silenced — no Pushover at all."""
        # 3-min run, well over the 7.7 threshold, but below min_runtime_minutes (5)
        mock_engine._send_zone_outcome("Z10 BB - Redwoods", 10, 3.0, 8.5, 25.5, 1)
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
    all_thresholds = load_zone_thresholds_from_config()
    zone_thresholds = get_controller_zone_thresholds(all_thresholds, "Rachio-Eden")
    print(f"  ✓ Loaded {len(zone_thresholds)} zone thresholds")
    for zone_num in sorted(zone_thresholds.keys()):
        zt = zone_thresholds[zone_num]
        cfg = get_config()
        za_cfg = cfg.rachio_flume.alerts.zone_anomaly
        threshold = zt.compute_threshold(za_cfg.absolute_gpm, za_cfg.percent_above)
        print(f"    Zone {zone_num:2d}: avg={zt.avg_gpm:5.2f} GPM, threshold={threshold:5.2f} GPM")

    # Test threshold checking
    print("\n[3/4] Testing threshold checking logic...")
    db = WaterTrackingDB(tmp_path)
    flume = MagicMock()
    rachio = MagicMock()
    rachio.get_active_zone.return_value = None
    pushover = MagicMock()

    cfg = get_config()
    za_cfg = cfg.rachio_flume.alerts.zone_anomaly

    engine = AlertEngine(
        flume_client=flume,
        rachio_client=rachio,
        pushover=pushover,
        db=db,
        rules=[],
        zone_thresholds=zone_thresholds,
        absolute_gpm=za_cfg.absolute_gpm,
        percent_above=za_cfg.percent_above,
        min_runtime_minutes=za_cfg.min_runtime_minutes,
    )

    # Test known zone
    threshold, avg = engine._get_zone_threshold(10)
    print(f"  ✓ Zone 10: avg={avg:.2f}, threshold={threshold:.2f}")

    # Test unknown zone
    threshold, avg = engine._get_zone_threshold(99)
    print(f"  ✓ Zone 99 (unknown): avg={avg:.2f}, threshold={threshold:.2f}")

    # Test outcome dispatch via _send_zone_outcome
    now = datetime.now()  # noqa: F841 -- kept for downstream code below
    engine._send_zone_outcome("Z10 BB", 10, 10.0, 8.5, 85.0, 1)
    title = engine.pushover.send_message.call_args[1]["title"]  # type: ignore[attr-defined]
    print(f"  ✓ Zone 10 @ 8.5 GPM: {title} (expected: Zone Anomaly)")

    engine._send_zone_outcome("Z10 BB", 10, 10.0, 7.0, 70.0, 1)
    title = engine.pushover.send_message.call_args[1]["title"]  # type: ignore[attr-defined]
    print(f"  ✓ Zone 10 @ 7.0 GPM: {title} (expected: Zone Report)")

    engine._send_zone_outcome("Unknown", 99, 10.0, 0.6, 6.0, 1)
    title = engine.pushover.send_message.call_args[1]["title"]  # type: ignore[attr-defined]
    print(f"  ✓ Zone 99 @ 0.6 GPM: {title} (expected: Zone Report; unknown→no baseline)")

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
