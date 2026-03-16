"""Tests for Samsung Frame TV CLI handlers."""

import argparse

import pytest
from unittest.mock import Mock, patch, MagicMock

from SamsungFrame.manage_samsung import tv_connection, reboot_tv, show_status, list_art


class TestTvConnection:
    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_success(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = True
        mock_client.host = "192.168.1.4"
        mock_cls.return_value = mock_client

        with tv_connection() as client:
            assert client is mock_client

        mock_client.close.assert_called_once()

    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_connect_fails_raises(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = False
        mock_client.host = "192.168.1.4"
        mock_cls.return_value = mock_client

        with pytest.raises(ConnectionError, match="Failed to get TV ready"):
            with tv_connection() as _client:
                pass

        mock_client.close.assert_called_once()

    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_closes_on_exception(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = True
        mock_client.host = "192.168.1.4"
        mock_cls.return_value = mock_client

        with pytest.raises(ValueError):
            with tv_connection() as _client:
                raise ValueError("boom")

        mock_client.close.assert_called_once()


class TestRebootTvHandler:
    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_connect_fails_returns_1(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = False
        mock_client.host = "192.168.1.4"
        mock_cls.return_value = mock_client

        args = argparse.Namespace()
        result = reboot_tv(args)

        assert result == 1

    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_reboot_success_returns_0(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = True
        mock_client.host = "192.168.1.4"
        mock_client._reboot_and_reconnect.return_value = True
        mock_cls.return_value = mock_client

        args = argparse.Namespace()
        result = reboot_tv(args)

        assert result == 0

    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_reboot_failure_returns_1(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = True
        mock_client.host = "192.168.1.4"
        mock_client._reboot_and_reconnect.return_value = False
        mock_cls.return_value = mock_client

        args = argparse.Namespace()
        result = reboot_tv(args)

        assert result == 1


class TestShowStatusHandler:
    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_connect_fails_returns_1(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = False
        mock_client.host = "192.168.1.4"
        mock_cls.return_value = mock_client

        args = argparse.Namespace()
        result = show_status(args)

        assert result == 1

    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_success_returns_0(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = True
        mock_client.host = "192.168.1.4"
        mock_client.get_device_info.return_value = {
            "device": {"modelName": "Frame", "FrameTVSupport": "true"}
        }
        mock_client.get_available_art.return_value = [{"content_id": "MY_F001"}]
        mock_client.check_art_support.return_value = True
        mock_cls.return_value = mock_client

        args = argparse.Namespace()
        result = show_status(args)

        assert result == 0


class TestListArtHandler:
    @patch("SamsungFrame.manage_samsung.SamsungFrameClient")
    def test_success_returns_0(self, mock_cls: Mock) -> None:
        mock_client = MagicMock()
        mock_client.connect_ready.return_value = True
        mock_client.host = "192.168.1.4"
        mock_client.get_available_art.return_value = [{"content_id": "MY_F001"}]
        mock_cls.return_value = mock_client

        args = argparse.Namespace()
        result = list_art(args)

        assert result == 0
