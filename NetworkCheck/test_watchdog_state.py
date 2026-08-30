"""Tests for watchdog state persistence.

The failure modes here are quiet ones: a field that does not round-trip
disables whatever depends on it, and a corrupt file can crash the watchdog at
the one moment it most needs to keep running.
"""

import json
import logging
from pathlib import Path

from NetworkCheck.conftest import HOUR, NOW
from NetworkCheck.watchdog_state import WatchdogState, load_state, save_state


def test_every_field_survives_a_round_trip(tmp_path: Path, logger: logging.Logger) -> None:
    """Guards the whole dataclass, not one field.

    Loading used to name each key by hand, so a field added later serialized
    fine and loaded back as None. Building from the field list also makes
    retired fields harmless, which is what lets an in-place upgrade drop
    last_heartbeat_ts from an existing state file without a migration.
    """
    path = str(tmp_path / "state.json")
    original = WatchdogState(
        down_since=NOW - HOUR,
        last_action_ts=NOW - 2 * HOUR,
        actions=[{"ts": NOW - 2 * HOUR}],
        pending=[{"ts": NOW, "message": "m", "title": "t", "priority": 1}],
    )
    save_state(path, original, logger)
    assert load_state(path, logger) == original


def test_missing_file_starts_fresh(tmp_path: Path, logger: logging.Logger) -> None:
    assert load_state(str(tmp_path / "absent.json"), logger) == WatchdogState()


def test_truncated_json_starts_fresh(tmp_path: Path, logger: logging.Logger) -> None:
    p = tmp_path / "state.json"
    p.write_text("{ truncated")
    assert load_state(str(p), logger) == WatchdogState()


def test_valid_json_that_is_not_an_object_starts_fresh(
    tmp_path: Path, logger: logging.Logger
) -> None:
    """`[1, 2]` parses fine, then .items() would raise outside the except."""
    p = tmp_path / "state.json"
    p.write_text("[1, 2]")
    assert load_state(str(p), logger) == WatchdogState()


def test_unknown_keys_are_ignored(tmp_path: Path, logger: logging.Logger) -> None:
    """Both directions: a newer file, and a retired field from an older one.

    `last_heartbeat_ts` is the real case -- prod state files still carry it
    after the beacon was removed, and they must load without a migration.
    """
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"down_since": NOW, "invented_later": 42, "last_heartbeat_ts": 1.0}))
    assert load_state(str(p), logger).down_since == NOW


def test_record_action_prunes_beyond_24h() -> None:
    state = WatchdogState(actions=[{"ts": NOW - 30 * HOUR}])
    state.record_action(NOW)
    assert [a["ts"] for a in state.actions] == [NOW]
    assert state.last_action_ts == NOW


def test_recent_actions_window() -> None:
    state = WatchdogState(actions=[{"ts": NOW - 30 * HOUR}, {"ts": NOW - HOUR}])
    assert len(state.recent_actions(NOW)) == 1


def test_saved_file_is_valid_json(tmp_path: Path, logger: logging.Logger) -> None:
    path = str(tmp_path / "state.json")
    save_state(path, WatchdogState(down_since=NOW), logger)
    assert json.loads(Path(path).read_text())["down_since"] == NOW
