#!/usr/bin/env python3
"""Tests for HeartbeatMonitor flap-suppression logic."""

from typing import List
from unittest.mock import MagicMock

import pytest

from NodeCheck.heartbeat_nodes import HeartbeatMonitor


def _fake_node(name: str, healthy_sequence: List[bool]) -> MagicMock:
    """Build a mock node whose heartbeat() returns the given sequence in order."""
    node = MagicMock()
    node.name = name
    node.config.ip = f"192.0.2.{abs(hash(name)) % 200 + 1}"
    node.heartbeat.side_effect = healthy_sequence
    return node


def _monitor(nodes: List[MagicMock]) -> HeartbeatMonitor:
    """Construct a HeartbeatMonitor bypassing __init__ (no config, no pushover)."""
    monitor = HeartbeatMonitor.__new__(HeartbeatMonitor)
    monitor.specific_nodes = None
    monitor.pushover = MagicMock()
    monitor.monitored_nodes = nodes
    monitor.last_down_nodes = set()
    monitor.last_notification_time = None
    monitor.consecutive_down = {}
    return monitor


class TestFlapSuppression:
    def test_single_down_probe_is_suppressed(self) -> None:
        """One failing probe should NOT surface as down (streak=1 < 2)."""
        node = _fake_node("Phone", [False])
        monitor = _monitor([node])

        assert monitor.check_monitored_nodes() == set()
        assert monitor.consecutive_down["Phone"] == 1

    def test_two_consecutive_down_probes_alert(self) -> None:
        """Two consecutive failures surface the node as down."""
        node = _fake_node("Phone", [False, False])
        monitor = _monitor([node])

        assert monitor.check_monitored_nodes() == set()
        assert monitor.check_monitored_nodes() == {"Phone"}
        assert monitor.consecutive_down["Phone"] == 2

    def test_recovery_resets_streak(self) -> None:
        """A successful probe between failures resets the streak."""
        node = _fake_node("Phone", [False, True, False])
        monitor = _monitor([node])

        assert monitor.check_monitored_nodes() == set()  # streak=1, suppressed
        assert monitor.check_monitored_nodes() == set()  # healthy, reset
        assert monitor.consecutive_down["Phone"] == 0
        assert monitor.check_monitored_nodes() == set()  # streak=1 again, suppressed

    def test_exception_counts_as_down(self) -> None:
        """Uncaught heartbeat exception is treated as a failing probe."""
        node = _fake_node("Broken", [False])
        node.heartbeat.side_effect = RuntimeError("boom")
        monitor = _monitor([node])

        assert monitor.check_monitored_nodes() == set()
        assert monitor.consecutive_down["Broken"] == 1

    def test_mixed_nodes_independent_streaks(self) -> None:
        """Streaks are tracked independently per node."""
        healthy = _fake_node("Server", [True, True])
        flaky = _fake_node("Phone", [False, False])
        monitor = _monitor([healthy, flaky])

        assert monitor.check_monitored_nodes() == set()
        assert monitor.check_monitored_nodes() == {"Phone"}
        assert monitor.consecutive_down["Server"] == 0
        assert monitor.consecutive_down["Phone"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
