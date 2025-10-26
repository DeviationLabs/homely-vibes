#!/usr/bin/env python3
import pytest
from unittest.mock import Mock, patch
from lib.Constants import NodeConfig
from lib.MyPushover import Pushover
from NodeCheck.manage_nodes import NodeChecker
from NodeCheck.nodes import FoscamNode, WindowsNode


class TestNodeBase:
    @pytest.fixture
    def mock_pushover(self):
        return Mock(spec=Pushover)

    @pytest.fixture
    def foscam_config(self):
        return NodeConfig("192.168.1.51", "foscam", "testuser", "testpass")

    @pytest.fixture
    def windows_config(self):
        return NodeConfig("192.168.1.100", "windows", "testuser", "testpass")


class TestFoscamNode(TestNodeBase):
    def test_init(self, foscam_config, mock_pushover):
        node = FoscamNode("TestCam", foscam_config, mock_pushover)
        assert node.name == "TestCam"
        assert node.ip == "192.168.1.51"
        assert node.config == foscam_config
        assert node.pushover == mock_pushover
        assert node.is_online is False

    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_check_state_success(self, mock_ping, foscam_config, mock_pushover):
        mock_ping.return_value = True
        node = FoscamNode("TestCam", foscam_config, mock_pushover)

        result = node.check_state(desired_up=True, attempts=1)

        assert result is True
        assert node.is_online is True
        mock_ping.assert_called_once_with(node="192.168.1.51", desired_up=True)

    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_check_state_failure(self, mock_ping, foscam_config, mock_pushover):
        mock_ping.return_value = False
        node = FoscamNode("TestCam", foscam_config, mock_pushover)

        result = node.check_state(desired_up=True, attempts=2)

        assert result is False
        assert node.is_online is False
        assert mock_ping.call_count == 2

    @patch("NodeCheck.check_nodes.NetHelpers.http_req")
    def test_reboot_node_success(self, mock_http_req, foscam_config, mock_pushover):
        mock_http_req.return_value = "success"
        node = FoscamNode("TestCam", foscam_config, mock_pushover)

        result = node.reboot_node()

        assert "success" in result
        expected_cmd = "http://192.168.1.51:88//cgi-bin/CGIProxy.fcgi?cmd=rebootSystem&usr=testuser&pwd=testpass"
        mock_http_req.assert_called_once_with(expected_cmd)

    @patch("NodeCheck.check_nodes.NetHelpers.http_req")
    def test_reboot_node_failure(self, mock_http_req, foscam_config, mock_pushover):
        mock_http_req.side_effect = OSError("Connection failed")
        node = FoscamNode("TestCam", foscam_config, mock_pushover)

        result = node.reboot_node()

        assert "ERROR" in result
        assert "TestCam" in result

    @patch("lib.FoscamImager.FoscamImager")
    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_heartbeat_success(self, mock_ping, mock_imager_class, foscam_config, mock_pushover):
        # Mock ping success and image capture success
        mock_ping.return_value = True
        mock_imager = Mock()
        mock_imager.getImage.return_value = "image_data"
        mock_imager_class.return_value = mock_imager

        node = FoscamNode("TestCam", foscam_config, mock_pushover)
        result = node.heartbeat()

        assert result is True
        mock_ping.assert_called_once_with(node="192.168.1.51", desired_up=True)
        mock_imager_class.assert_called_once_with("192.168.1.51", False)
        mock_imager.getImage.assert_called_once()

    @patch("lib.FoscamImager.FoscamImager")
    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_heartbeat_ping_failure(
        self, mock_ping, mock_imager_class, foscam_config, mock_pushover
    ):
        # Mock ping failure - should not even try image capture
        mock_ping.return_value = False

        node = FoscamNode("TestCam", foscam_config, mock_pushover)
        result = node.heartbeat()

        assert result is False
        mock_ping.assert_called_once_with(node="192.168.1.51", desired_up=True)
        mock_imager_class.assert_not_called()

    @patch("lib.FoscamImager.FoscamImager")
    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_heartbeat_image_failure(
        self, mock_ping, mock_imager_class, foscam_config, mock_pushover
    ):
        # Mock ping success but image capture failure
        mock_ping.return_value = True
        mock_imager = Mock()
        mock_imager.getImage.return_value = None
        mock_imager_class.return_value = mock_imager

        node = FoscamNode("TestCam", foscam_config, mock_pushover)
        result = node.heartbeat()

        assert result is False
        mock_pushover.send_message.assert_called_once()


class TestWindowsNode(TestNodeBase):
    def test_init(self, windows_config, mock_pushover):
        node = WindowsNode("TestWin", windows_config, mock_pushover)
        assert node.name == "TestWin"
        assert node.ip == "192.168.1.100"
        assert node.config == windows_config
        assert node.pushover == mock_pushover

    @patch("NodeCheck.check_nodes.NetHelpers.ssh_cmd")
    def test_reboot_node(self, mock_ssh_cmd, windows_config, mock_pushover):
        mock_ssh_cmd.return_value = "shutdown initiated"
        node = WindowsNode("TestWin", windows_config, mock_pushover)

        result = node.reboot_node()

        assert "shutdown initiated" in result
        mock_ssh_cmd.assert_called_once_with(
            "192.168.1.100",
            "testuser",
            "testpass",
            'cmd /c "shutdown /r /f & ping localhost -n 3 > nul"',
        )

    @patch("NodeCheck.check_nodes.NetHelpers.ssh_cmd")
    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_heartbeat_success(self, mock_ping, mock_ssh_cmd, windows_config, mock_pushover):
        # Mock ping success and SSH success
        mock_ping.return_value = True
        mock_ssh_cmd.return_value = "successful Statistics since 10/26/2024 12:00:00 PM"
        node = WindowsNode("TestWin", windows_config, mock_pushover)

        result = node.heartbeat()

        assert result is True
        mock_ping.assert_called_once_with(node="192.168.1.100", desired_up=True)
        mock_ssh_cmd.assert_called_once_with(
            "192.168.1.100", "testuser", "testpass", "net statistics workstation"
        )

    @patch("NodeCheck.check_nodes.NetHelpers.ssh_cmd")
    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_heartbeat_ping_failure(self, mock_ping, mock_ssh_cmd, windows_config, mock_pushover):
        # Mock ping failure - should not try SSH
        mock_ping.return_value = False
        node = WindowsNode("TestWin", windows_config, mock_pushover)

        result = node.heartbeat()

        assert result is False
        mock_ping.assert_called_once_with(node="192.168.1.100", desired_up=True)
        mock_ssh_cmd.assert_not_called()

    @patch("NodeCheck.check_nodes.NetHelpers.ssh_cmd")
    @patch("NodeCheck.check_nodes.NetHelpers.ping_output")
    def test_heartbeat_ssh_failure(self, mock_ping, mock_ssh_cmd, windows_config, mock_pushover):
        # Mock ping success but SSH failure
        mock_ping.return_value = True
        mock_ssh_cmd.return_value = "error: no statistics available"
        node = WindowsNode("TestWin", windows_config, mock_pushover)

        result = node.heartbeat()

        assert result is False


class TestNodeChecker:
    @patch(
        "NodeCheck.manage_nodes.Constants.NODE_CONFIGS",
        {
            "TestCam": NodeConfig("192.168.1.51", "foscam", "user", "pass"),
            "TestWin": NodeConfig("192.168.1.100", "windows", "user", "pass"),
        },
    )
    @patch("NodeCheck.manage_nodes.Pushover")
    def test_init_foscam_mode(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        checker = NodeChecker("foscam")

        assert checker.mode == "foscam"
        assert len(checker.nodes) == 1
        assert isinstance(checker.nodes[0], FoscamNode)
        assert checker.nodes[0].name == "TestCam"

    @patch(
        "NodeCheck.manage_nodes.Constants.NODE_CONFIGS",
        {
            "TestCam": NodeConfig("192.168.1.51", "foscam", "user", "pass"),
            "TestWin": NodeConfig("192.168.1.100", "windows", "user", "pass"),
        },
    )
    @patch("NodeCheck.manage_nodes.Pushover")
    def test_init_windows_mode(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        checker = NodeChecker("windows")

        assert checker.mode == "windows"
        assert len(checker.nodes) == 1
        assert isinstance(checker.nodes[0], WindowsNode)
        assert checker.nodes[0].name == "TestWin"

    @patch(
        "NodeCheck.manage_nodes.Constants.NODE_CONFIGS",
        {"TestCam": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.manage_nodes.Pushover")
    def test_check_connectivity_success(self, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        checker = NodeChecker("foscam")

        with patch.object(checker.nodes[0], "heartbeat", return_value=True):
            result = checker.check_connectivity()

            assert result is True
            assert "TestCam online" in "\n".join(checker.messages)

    @patch(
        "NodeCheck.manage_nodes.Constants.NODE_CONFIGS",
        {"TestCam": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.manage_nodes.Pushover")
    def test_check_connectivity_failure(self, mock_pushover_class):
        mock_pushover = Mock()
        mock_pushover_class.return_value = mock_pushover
        checker = NodeChecker("foscam")

        with patch.object(checker.nodes[0], "heartbeat", return_value=False):
            result = checker.check_connectivity()

            assert result is False
            assert "ERROR" in "\n".join(checker.messages)
            mock_pushover.send_message.assert_called_once()

    @patch(
        "NodeCheck.manage_nodes.Constants.NODE_CONFIGS",
        {"TestCam": NodeConfig("192.168.1.51", "foscam", "user", "pass")},
    )
    @patch("NodeCheck.manage_nodes.Pushover")
    @patch("NodeCheck.check_nodes.Mailer.sendmail")
    def test_generate_report(self, mock_sendmail, mock_pushover_class):
        mock_pushover_class.return_value = Mock()
        checker = NodeChecker("foscam")
        checker.messages = ["Test message"]

        checker.generate_report(system_healthy=True, always_email=False)

        mock_sendmail.assert_called_once_with(
            topic="[NodeCheck-foscam]",
            alert=False,
            message="Test message\nAll is well",
            always_email=False,
        )
        assert "All is well" in "\n".join(checker.messages)


if __name__ == "__main__":
    pytest.main([__file__])
