#!/usr/bin/env python3
import pytest
from unittest.mock import Mock, patch, call
from lib.Constants import NodeConfig
from lib.MyPushover import Pushover
from NodeCheck.heartbeat_nodes import HeartbeatMonitor


class TestHeartbeatMonitor:
    @pytest.fixture
    def mock_pushover(self):
        return Mock(spec=Pushover)

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {
            "TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass"),
            "TestCam2": NodeConfig("192.168.1.52", "foscam", "user", "pass"),
        },
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_init_all_nodes(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        monitor = HeartbeatMonitor("foscam", 30)

        assert monitor.mode == "foscam"
        assert monitor.poll_time == 30
        assert monitor.specific_nodes is None
        assert len(monitor.checker.nodes) == 2
        assert monitor.last_down_nodes == set()

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {
            "TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass"),
            "TestCam2": NodeConfig("192.168.1.52", "foscam", "user", "pass"),
        },
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_init_specific_nodes(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        monitor = HeartbeatMonitor("foscam", 30, ["TestCam1"])

        assert len(monitor.checker.nodes) == 1
        assert monitor.checker.nodes[0].name == "TestCam1"

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {"TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_init_invalid_nodes(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()

        with pytest.raises(ValueError, match="No valid nodes found"):
            HeartbeatMonitor("foscam", 30, ["NonExistent"])

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {
            "TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass"),
            "TestCam2": NodeConfig("192.168.1.52", "foscam", "user", "pass"),
        },
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_check_all_nodes_healthy(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        monitor = HeartbeatMonitor("foscam", 30)

        # Mock all nodes as healthy
        for node in monitor.checker.nodes:
            node.heartbeat = Mock(return_value=True)

        down_nodes = monitor.check_all_nodes()

        assert down_nodes == set()

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {
            "TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass"),
            "TestCam2": NodeConfig("192.168.1.52", "foscam", "user", "pass"),
        },
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_check_all_nodes_some_down(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        monitor = HeartbeatMonitor("foscam", 30)

        # Mock first node down, second node healthy
        monitor.checker.nodes[0].heartbeat = Mock(return_value=False)
        monitor.checker.nodes[1].heartbeat = Mock(return_value=True)

        down_nodes = monitor.check_all_nodes()

        assert down_nodes == {"TestCam1"}

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {"TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_check_all_nodes_exception(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        monitor = HeartbeatMonitor("foscam", 30)

        # Mock node to raise exception
        monitor.checker.nodes[0].heartbeat = Mock(side_effect=Exception("Network error"))

        down_nodes = monitor.check_all_nodes()

        assert down_nodes == {"TestCam1"}

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {"TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_send_notification_single_node(self, mock_pushover_class):
        mock_pushover = Mock()
        mock_pushover_class.return_value = mock_pushover
        monitor = HeartbeatMonitor("foscam", 30)

        monitor.send_notification({"TestCam1"})

        mock_pushover.send_message.assert_called_once_with(
            "Node TestCam1 is down", title="Foscam Node Down", priority=1
        )

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {
            "TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass"),
            "TestCam2": NodeConfig("192.168.1.52", "foscam", "user", "pass"),
        },
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_send_notification_multiple_nodes(self, mock_pushover_class):
        mock_pushover = Mock()
        mock_pushover_class.return_value = mock_pushover
        monitor = HeartbeatMonitor("foscam", 30)

        monitor.send_notification({"TestCam1", "TestCam2"})

        mock_pushover.send_message.assert_called_once_with(
            "2 nodes are down: TestCam1, TestCam2", title="Foscam Nodes Down", priority=1
        )

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {"TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    def test_send_notification_no_nodes(self, mock_pushover_class):
        mock_pushover = Mock()
        mock_pushover_class.return_value = mock_pushover
        monitor = HeartbeatMonitor("foscam", 30)

        monitor.send_notification(set())

        mock_pushover.send_message.assert_not_called()

    @patch(
        "NodeCheck.heartbeat_nodes.Constants.NODE_CONFIGS",
        {"TestCam1": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.heartbeat_nodes.Pushover")
    @patch("NodeCheck.heartbeat_nodes.time.sleep")
    def test_run_continuous_monitoring_cycle(self, mock_sleep, mock_pushover_class):
        mock_pushover = Mock()
        mock_pushover_class.return_value = mock_pushover
        monitor = HeartbeatMonitor("foscam", 30)

        # Mock sleep to raise KeyboardInterrupt after 2 cycles
        mock_sleep.side_effect = [None, KeyboardInterrupt()]

        # Mock node to be down then healthy
        monitor.checker.nodes[0].heartbeat = Mock(side_effect=[False, True])

        # Should exit after KeyboardInterrupt
        monitor.run_continuous_monitoring()

        # Should have called heartbeat twice (down, then healthy)
        assert monitor.checker.nodes[0].heartbeat.call_count == 2

        # Should have sent one notification for down node
        mock_pushover.send_message.assert_called_once_with(
            "Node TestCam1 is down", title="Foscam Node Down", priority=1
        )

        # Should have slept twice (after each check)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(30), call(30)])


if __name__ == "__main__":
    pytest.main([__file__])
