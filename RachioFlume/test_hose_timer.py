"""Tests for the Rachio Smart Hose Timer integration."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock

import pytest

from RachioFlume.alert_rules import ZoneThreshold
from RachioFlume.data_storage import WaterTrackingDB
from RachioFlume.hose_timer_processor import HoseTimerProcessor, _state_key
from RachioFlume.rachio_hose_client import HoseValve, RachioHoseClient


@pytest.fixture
def tmp_db() -> Iterator[WaterTrackingDB]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        yield WaterTrackingDB(path)
    finally:
        Path(path).unlink(missing_ok=True)


def _valve(action: Dict[str, Any] | None = None) -> HoseValve:
    return HoseValve(
        id="valve-1",
        base_station_id="bs-1",
        base_station_label="Hose Drip Jasmine",
        name="Upper Deck Planters",
        default_runtime_seconds=600,
        detect_flow=True,
        battery_status="GOOD",
        connected=True,
        last_watering_action=action,
    )


def _make_processor(
    tmp_db: WaterTrackingDB, valve: HoseValve
) -> tuple[HoseTimerProcessor, MagicMock]:
    client = MagicMock(spec=RachioHoseClient)
    client.label = "Hose Drip Jasmine"
    client.list_valves.return_value = [valve]
    pushover = MagicMock()
    thresholds = {
        "Upper Deck Planters": ZoneThreshold(
            zone_key="Upper Deck Planters", name="UDP", avg_gpm=0.5
        )
    }
    proc = HoseTimerProcessor(client=client, pushover=pushover, db=tmp_db, thresholds=thresholds)
    return proc, pushover


class TestParseAction:
    def test_parse_start_handles_trailing_z(self) -> None:
        action = {"start": "2026-06-27T07:46:46Z", "durationSeconds": "30"}
        dt = RachioHoseClient.parse_action_start(action)
        assert dt is not None
        # Result is naive local; just verify it round-trips
        assert dt.year == 2026 and dt.month == 6 and dt.day == 27

    def test_parse_duration_handles_string(self) -> None:
        assert RachioHoseClient.parse_action_duration({"durationSeconds": "120"}) == 120
        assert RachioHoseClient.parse_action_duration({"durationSeconds": 30}) == 30
        assert RachioHoseClient.parse_action_duration({}) == 0


class TestHoseTimerProcessor:
    def test_run_started_persists_state_and_event(self, tmp_db: WaterTrackingDB) -> None:
        action = {
            "start": "2026-06-27T07:46:46Z",
            "durationSeconds": "60",
            "reason": "QUICK_RUN",
            "flowDetected": False,
        }
        valve = _valve(action)
        proc, pushover = _make_processor(tmp_db, valve)

        results = proc.evaluate(now=datetime(2026, 6, 27, 7, 47, 0))

        assert len(results) == 1
        assert results[0]["action"] == "run_started"
        # No pushover on start, only on completion
        pushover.send_message.assert_not_called()
        # State key persisted
        blob = tmp_db.get_metadata(_state_key("valve-1"))
        assert blob is not None
        cached = json.loads(blob)
        assert cached["finalized"] is False
        assert cached["duration_seconds"] == 60

    def test_run_completed_sends_pushover_and_session(self, tmp_db: WaterTrackingDB) -> None:
        # Seed processor with a started run
        action = {
            "start": "2026-06-27T07:46:46Z",
            "durationSeconds": "60",
            "reason": "QUICK_RUN",
            "flowDetected": True,
        }
        valve = _valve(action)
        proc, pushover = _make_processor(tmp_db, valve)
        proc.evaluate(now=datetime(2026, 6, 27, 7, 47, 0))

        # Next poll: action gone, now > start + duration
        proc.client.list_valves.return_value = [_valve(action=None)]  # type: ignore[attr-defined]
        results = proc.evaluate(now=datetime(2026, 6, 27, 7, 49, 0))

        assert results[0]["action"] == "run_completed"
        assert results[0]["flow_detected"] is True
        pushover.send_message.assert_called_once()
        # Verify pushover message contains threshold and device label
        call_args = pushover.send_message.call_args
        msg = call_args[0][0]
        assert "Hose Drip Jasmine" in msg
        assert "Upper Deck Planters" in msg
        assert "thresh 0.50" in msg  # configured baseline appears in flow line
        assert "Avg flow:" in msg
        assert "Total:" in msg
        assert "Flow sensor: detected" in msg
        # Session row persisted
        sessions = tmp_db.get_hose_zone_sessions(
            datetime(2026, 6, 27, 0, 0, 0), datetime(2026, 6, 27, 23, 59, 0)
        )
        assert len(sessions) == 1
        assert sessions[0]["duration_seconds"] == 60
        assert sessions[0]["flow_detected"] == 1

    def test_no_pushover_when_no_baseline(self, tmp_db: WaterTrackingDB) -> None:
        action = {
            "start": "2026-06-27T07:46:46Z",
            "durationSeconds": "60",
            "reason": "QUICK_RUN",
            "flowDetected": None,
        }
        valve = _valve(action)
        client = MagicMock(spec=RachioHoseClient)
        client.label = "Hose Drip Jasmine"
        client.list_valves.return_value = [valve]
        pushover = MagicMock()
        proc = HoseTimerProcessor(client=client, pushover=pushover, db=tmp_db, thresholds={})

        proc.evaluate(now=datetime(2026, 6, 27, 7, 47, 0))
        client.list_valves.return_value = [_valve(action=None)]
        proc.evaluate(now=datetime(2026, 6, 27, 7, 49, 0))

        pushover.send_message.assert_called_once()
        msg = pushover.send_message.call_args[0][0]
        # No baseline -> just "Avg flow: X.XX GPM" without (thresh ...)
        assert "Avg flow:" in msg
        assert "thresh" not in msg

    def test_completion_only_after_window_elapses(self, tmp_db: WaterTrackingDB) -> None:
        """If action disappears before start+duration, don't finalize yet.

        The processor converts the UTC action.start to local naive time.
        Use the parsed start as the anchor so this test is tz-independent.
        """
        action = {
            "start": "2026-06-27T07:46:46Z",
            "durationSeconds": "600",  # 10-minute run
            "reason": "QUICK_RUN",
            "flowDetected": False,
        }
        local_start = RachioHoseClient.parse_action_start(action)
        assert local_start is not None
        valve = _valve(action)
        proc, pushover = _make_processor(tmp_db, valve)
        proc.evaluate(now=local_start + timedelta(seconds=14))

        # Action vanishes 30s later, but window not yet elapsed (only 44s in)
        proc.client.list_valves.return_value = [_valve(action=None)]  # type: ignore[attr-defined]
        results = proc.evaluate(now=local_start + timedelta(seconds=44))
        assert results[0]["action"] == "nothing"
        pushover.send_message.assert_not_called()

        # Now jump past the run window (>10 min in)
        results = proc.evaluate(now=local_start + timedelta(minutes=11))
        assert results[0]["action"] == "run_completed"
        pushover.send_message.assert_called_once()

    def test_dry_run_does_not_persist(self, tmp_db: WaterTrackingDB) -> None:
        action = {
            "start": "2026-06-27T07:46:46Z",
            "durationSeconds": "30",
            "reason": "QUICK_RUN",
            "flowDetected": False,
        }
        valve = _valve(action)
        proc, pushover = _make_processor(tmp_db, valve)

        results = proc.evaluate(now=datetime(2026, 6, 27, 7, 47, 0), dry_run=True)
        assert results[0]["action"] == "run_started"
        # No state persisted
        assert tmp_db.get_metadata(_state_key("valve-1")) is None
        pushover.send_message.assert_not_called()


class TestListValvesParsing:
    def test_list_valves_handles_real_response(self) -> None:
        """Verify the parser handles the real Rachio listValves response shape."""
        import requests
        from unittest.mock import patch

        sample = {
            "valves": [
                {
                    "id": "v1",
                    "name": "Upper Deck Planters",
                    "detectFlow": True,
                    "state": {
                        "reportedState": {
                            "connected": True,
                            "defaultRuntimeSeconds": "600",
                            "batteryStatus": "GOOD",
                            "lastWateringAction": {
                                "start": "2026-06-27T07:46:46Z",
                                "durationSeconds": "30",
                                "reason": "QUICK_RUN",
                                "flowDetected": False,
                            },
                        }
                    },
                }
            ]
        }
        with patch.object(requests, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = sample
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            client = RachioHoseClient(api_key="k", base_station_id="bs1", label="T")  # nosecret
            valves = client.list_valves()
            assert len(valves) == 1
            v = valves[0]
            assert v.name == "Upper Deck Planters"
            assert v.default_runtime_seconds == 600
            assert v.detect_flow is True
            assert v.battery_status == "GOOD"
            assert v.last_watering_action is not None
            assert v.last_watering_action["reason"] == "QUICK_RUN"
