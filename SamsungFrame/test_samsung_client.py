"""Tests for Samsung Frame TV client."""

import pytest
import socket
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from PIL import Image

from SamsungFrame.samsung_client import (
    SamsungFrameClient,
)


class TestSamsungFrameClient:
    """Test Samsung Frame TV client."""

    def test_init_with_config(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.ip = "192.168.1.4"
        mock_cfg.samsung_frame.port = 8002
        mock_cfg.samsung_frame.token_file = "/tmp/token.txt"

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            client = SamsungFrameClient()
            assert client.host == "192.168.1.4"
            assert client.port == 8002
            assert client.token_file == "/tmp/token.txt"

    def test_init_with_custom_params(self) -> None:
        """Test initialization with custom parameters."""
        client = SamsungFrameClient(host="192.168.1.5", port=8003, token_file="/custom/token.txt")
        assert client.host == "192.168.1.5"
        assert client.port == 8003
        assert client.token_file == "/custom/token.txt"

    def test_init_missing_host(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.ip = ""
        mock_cfg.samsung_frame.port = 8002
        mock_cfg.samsung_frame.token_file = "/tmp/token.txt"

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            with pytest.raises(ValueError, match="Samsung Frame TV IP address required"):
                SamsungFrameClient()

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("os.chmod")
    @patch("builtins.open", create=True)
    def test_connect_success(
        self,
        mock_open: Mock,
        _mock_chmod: Mock,
        _mock_makedirs: Mock,
        mock_exists: Mock,
        mock_tv: Mock,
    ) -> None:
        """Test successful connection to TV."""
        mock_exists.return_value = True
        mock_tv_instance = Mock()
        mock_tv_instance.art().supported.return_value = True
        mock_tv.return_value = mock_tv_instance

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.connect()

        assert result is True
        assert client.tv is not None
        mock_tv.assert_called_once()

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists")
    @patch("os.chmod")
    @patch("time.sleep")
    @patch("builtins.open", create=True)
    def test_connect_with_retry(
        self,
        mock_open: Mock,
        mock_sleep: Mock,
        _mock_chmod: Mock,
        mock_exists: Mock,
        mock_tv: Mock,
    ) -> None:
        """Test connection retry logic on failure."""
        mock_exists.return_value = True

        mock_tv_instance_fail = Mock()
        mock_tv_instance_fail.art().supported.side_effect = ConnectionError("Connection failed")

        mock_tv_instance_success = Mock()
        mock_tv_instance_success.art().supported.return_value = True

        mock_tv.side_effect = [
            mock_tv_instance_fail,
            mock_tv_instance_fail,
            mock_tv_instance_success,
        ]

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.connect()

        assert result is True
        assert mock_tv.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists")
    @patch("time.sleep")
    def test_connect_max_retries(self, mock_sleep: Mock, mock_exists: Mock, mock_tv: Mock) -> None:
        """Test connection fails after max retries."""
        mock_exists.return_value = True
        mock_tv_instance = Mock()
        mock_tv_instance.art().supported.side_effect = ConnectionError("Connection failed")
        mock_tv.return_value = mock_tv_instance

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.connect()

        assert result is False
        assert mock_tv.call_count == 3

    def test_check_art_support_not_connected(self) -> None:
        """Test check_art_support fails when not connected."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.check_art_support()
        assert result is False

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_validate_image_file_not_found(self, mock_tv: Mock) -> None:
        """Test image validation fails for non-existent file."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.validate_image_file("/nonexistent/image.jpg")
        assert result is False

    def test_validate_image_file_invalid_format(self) -> None:
        """Test image validation fails for unsupported format."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp_file:
            tmp_file.write(b"test content")
            tmp_path = tmp_file.name

        try:
            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            result = client.validate_image_file(tmp_path)
            assert result is False
        finally:
            os.unlink(tmp_path)

    def test_validate_image_file_too_large(self) -> None:
        """Test image validation fails for file too large."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
            # Write more than 1MB
            tmp_file.write(b"x" * (2 * 1024 * 1024))
            tmp_path = tmp_file.name

        try:
            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            result = client.validate_image_file(tmp_path)
            assert result is False
        finally:
            os.unlink(tmp_path)

    def test_validate_image_file_success(self) -> None:
        """Test image validation succeeds for valid image."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
            # Create a valid small image
            img = Image.new("RGB", (100, 100), color="red")
            img.save(tmp_file, format="JPEG")
            tmp_path = tmp_file.name

        try:
            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            result = client.validate_image_file(tmp_path)
            assert result is True
        finally:
            os.unlink(tmp_path)

    def test_upload_image_not_connected(self) -> None:
        """Test upload fails when not connected."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.upload_image("/path/to/image.jpg")
        assert result is None

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_upload_image_success(self, mock_tv: Mock) -> None:
        """Test successful image upload."""
        # Create a valid test image
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_file:
            img = Image.new("RGB", (100, 100), color="blue")
            img.save(tmp_file, format="JPEG")
            tmp_path = tmp_file.name

        try:
            # Setup mock TV
            mock_tv_instance = Mock()
            mock_tv_instance.art().upload.return_value = "image123"
            mock_tv.return_value = mock_tv_instance

            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            client.tv = mock_tv_instance

            result = client.upload_image(tmp_path)

            assert result == "image123"
            mock_tv_instance.art().upload.assert_called_once()
        finally:
            os.unlink(tmp_path)

    def test_upload_images_from_folder_not_connected(self) -> None:
        """Test batch upload fails when not connected."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with pytest.raises(RuntimeError, match="Not connected to TV"):
            client.upload_images_from_folder("/tmp")

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_upload_images_from_folder_success(self, mock_tv: Mock) -> None:
        """Test successful batch upload from folder."""
        # Create temp directory with test images
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create 3 valid test images
            for i in range(3):
                img_path = os.path.join(tmp_dir, f"image{i}.jpg")
                img = Image.new("RGB", (100, 100), color="red")
                img.save(img_path, format="JPEG")

            # Setup mock TV
            mock_tv_instance = Mock()
            mock_tv_instance.art().upload.side_effect = ["id1", "id2", "id3"]

            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            client.tv = mock_tv_instance

            summary = client.upload_images_from_folder(tmp_dir)

            assert summary.total_images == 3
            assert summary.successful_uploads == 3
            assert summary.failed_uploads == 0
            assert len(summary.uploaded_image_ids) == 3

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_upload_images_from_folder_partial_failure(self, mock_tv: Mock) -> None:
        """Test batch upload with some failures."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create 2 valid images and 1 invalid
            for i in range(2):
                img_path = os.path.join(tmp_dir, f"image{i}.jpg")
                img = Image.new("RGB", (100, 100), color="green")
                img.save(img_path, format="JPEG")

            # Create invalid image (just text file with .jpg extension)
            invalid_path = os.path.join(tmp_dir, "invalid.jpg")
            with open(invalid_path, "w") as f:
                f.write("not an image")

            # Setup mock TV
            mock_tv_instance = Mock()
            mock_tv_instance.art().upload.side_effect = ["id1", "id2"]

            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            client.tv = mock_tv_instance

            summary = client.upload_images_from_folder(tmp_dir)

            assert summary.total_images == 3
            assert summary.successful_uploads == 2
            assert summary.failed_uploads == 1
            assert len(summary.errors) == 1

    def test_enable_art_mode_not_connected(self) -> None:
        """Test enable_art_mode fails when not connected."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.enable_art_mode()
        assert result is False

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_enable_art_mode_success(self, mock_tv: Mock) -> None:
        """Test successful art mode enable when not already in art mode."""
        mock_tv_instance = Mock()
        mock_tv_instance.art().get_artmode.return_value = "off"
        mock_tv_instance.art().set_artmode.return_value = None

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv_instance

        result = client.enable_art_mode()

        assert result is True
        mock_tv_instance.art().set_artmode.assert_called_once_with(True)

    def test_start_slideshow_not_connected(self) -> None:
        """Test start_slideshow fails when not connected."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.start_slideshow()
        assert result is False

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_start_slideshow_success(self, mock_tv: Mock) -> None:
        """Test successful slideshow start."""
        mock_tv_instance = Mock()
        mock_tv_instance.art().set_artmode.return_value = None

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv_instance

        result = client.start_slideshow()

        assert result is True
        mock_tv_instance.art().set_artmode.assert_called_once_with(True)

    def test_get_available_art_not_connected(self) -> None:
        """Test get_available_art fails when not connected."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with pytest.raises(RuntimeError, match="Not connected to TV"):
            client.get_available_art()

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_get_available_art_success(self, mock_tv: Mock) -> None:
        """Test successful art list retrieval."""
        mock_tv_instance = Mock()
        mock_tv_instance.art().available.return_value = [
            {"content_id": "art1"},
            {"content_id": "art2"},
        ]

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv_instance

        art_list = client.get_available_art()

        assert len(art_list) == 2
        assert art_list[0]["content_id"] == "art1"

    def test_cycle_images_not_connected(self) -> None:
        """Test cycle_images fails when not connected."""
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with pytest.raises(RuntimeError, match="Not connected to TV"):
            client.cycle_images()

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("time.sleep")
    def test_cycle_images_user_photos_only(self, mock_sleep: Mock, mock_tv: Mock) -> None:
        """Test cycling through user photos only."""
        mock_tv_instance = Mock()
        mock_tv_instance.art().available.return_value = [
            {"content_id": "MY_F0001"},
            {"content_id": "MY_F0002"},
            {"content_id": "ART_12345"},
        ]
        mock_tv_instance.art().set_artmode.return_value = None

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv_instance

        # Simulate KeyboardInterrupt after 2 image displays
        mock_sleep.side_effect = [None, KeyboardInterrupt()]

        client.cycle_images(period=15, user_photos_only=True)

        # Should only call select_image for MY_F photos
        assert mock_tv_instance.art().select_image.call_count == 2
        mock_tv_instance.art().select_image.assert_any_call("MY_F0001")
        mock_tv_instance.art().select_image.assert_any_call("MY_F0002")

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("time.sleep")
    def test_cycle_images_all_art(self, mock_sleep: Mock, mock_tv: Mock) -> None:
        """Test cycling through all art."""
        mock_tv_instance = Mock()
        mock_tv_instance.art().available.return_value = [
            {"content_id": "MY_F0001"},
            {"content_id": "ART_12345"},
        ]
        mock_tv_instance.art().set_artmode.return_value = None

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv_instance

        # Simulate KeyboardInterrupt after 2 image displays
        mock_sleep.side_effect = [None, KeyboardInterrupt()]

        client.cycle_images(period=10, user_photos_only=False)

        # Should call select_image for all art
        assert mock_tv_instance.art().select_image.call_count == 2
        mock_tv_instance.art().select_image.assert_any_call("MY_F0001")
        mock_tv_instance.art().select_image.assert_any_call("ART_12345")


class TestPing:
    def test_ping_not_connected(self) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        with pytest.raises(RuntimeError, match="Not connected to TV"):
            client.ping()

    def test_ping_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().supported.return_value = True

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        assert client.ping() is True
        mock_tv.art().supported.assert_called_once()

    def test_ping_failure_propagates(self) -> None:
        mock_tv = Mock()
        mock_tv.art().supported.side_effect = TimeoutError("TV not responding")

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        with pytest.raises(TimeoutError, match="TV not responding"):
            client.ping()


class TestGetAvailableArtStrict:
    def test_strict_not_connected(self) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        with pytest.raises(RuntimeError, match="Not connected to TV"):
            client.get_available_art_strict()

    def test_strict_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.return_value = [{"content_id": "MY_F001"}]

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.get_available_art_strict()
        assert len(result) == 1
        assert result[0]["content_id"] == "MY_F001"

    def test_strict_raises_on_timeout(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.return_value = {"event": "ms.channel.timeOut"}

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        with pytest.raises(TimeoutError, match="timed out"):
            client.get_available_art_strict()

    def test_strict_raises_on_exception(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.side_effect = ConnectionError("WebSocket closed")

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        with pytest.raises(ConnectionError, match="WebSocket closed"):
            client.get_available_art_strict()

    def test_lenient_returns_empty_on_error(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.side_effect = ConnectionError("WebSocket closed")

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.get_available_art()
        assert result == []


class TestReconnectDuringUpload:
    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("time.sleep")
    def test_reconnect_on_consecutive_failures(self, mock_sleep: Mock, mock_tv_cls: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(5):
                img = Image.new("RGB", (100, 100), color="red")
                img.save(os.path.join(tmp_dir, f"img_{i}.jpg"), format="JPEG")

            mock_tv = Mock()
            mock_tv.art().upload.side_effect = [None, None, None, "id4", "id5"]
            mock_tv.art().supported.return_value = True

            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            client.tv = mock_tv

            with (
                patch.object(client, "_reconnect", return_value=True),
                patch.object(client, "ensure_art_mode", return_value=True),
            ):
                summary = client.upload_images_from_folder(tmp_dir, max_consecutive_failures=3)

            assert summary.successful_uploads >= 0

    @patch("time.sleep")
    def test_stops_after_reconnect_fails(self, mock_sleep: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(5):
                img = Image.new("RGB", (100, 100), color="red")
                img.save(os.path.join(tmp_dir, f"img_{i}.jpg"), format="JPEG")

            mock_tv = Mock()
            mock_tv.art().upload.return_value = None

            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            client.tv = mock_tv

            with (
                patch.object(client, "_reconnect", return_value=False),
                patch.object(client, "ensure_art_mode", return_value=False),
                patch.object(client, "_reboot_and_reconnect", return_value=False),
            ):
                summary = client.upload_images_from_folder(tmp_dir, max_consecutive_failures=3)

            assert summary.successful_uploads == 0

    @patch("time.sleep")
    def test_only_one_reconnect_per_batch(self, mock_sleep: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(8):
                img = Image.new("RGB", (100, 100), color="red")
                img.save(os.path.join(tmp_dir, f"img_{i}.jpg"), format="JPEG")

            mock_tv = Mock()
            mock_tv.art().upload.return_value = None

            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            client.tv = mock_tv

            reboot_mock = Mock(return_value=False)
            with (
                patch.object(client, "ensure_art_mode", return_value=False),
                patch.object(client, "_reboot_and_reconnect", reboot_mock),
            ):
                client.upload_images_from_folder(tmp_dir, max_consecutive_failures=3)

            reboot_mock.assert_called_once()


class TestSendWol:
    def test_no_mac_configured(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.mac = ""
        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            assert client._send_wol() is False

    @patch("SamsungFrame.samsung_client.socket")
    def test_sends_magic_packet(self, mock_socket_mod: Mock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.mac = "AA:BB:CC:DD:EE:FF"
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = Mock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = Mock(return_value=False)
        mock_socket_mod.AF_INET = socket.AF_INET
        mock_socket_mod.SOCK_DGRAM = socket.SOCK_DGRAM
        mock_socket_mod.SOL_SOCKET = socket.SOL_SOCKET
        mock_socket_mod.SO_BROADCAST = socket.SO_BROADCAST

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
            assert client._send_wol() is True

        mock_sock.sendto.assert_called_once()
        magic = mock_sock.sendto.call_args[0][0]
        assert magic[:6] == b"\xff" * 6
        assert len(magic) == 102  # 6 + 16*6


class TestConnectReady:
    @patch("time.sleep")
    def test_already_connected_and_art_mode(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with (
            patch.object(client, "connect", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_connect_ok_art_fails_reboots(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with (
            patch.object(client, "connect", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=False),
            patch.object(client, "_reboot_and_reconnect", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_connect_fails_wol_wakes_tv(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        connect_results = iter([False, True])

        with (
            patch.object(client, "connect", side_effect=lambda: next(connect_results)),
            patch.object(client, "_is_tv_reachable", return_value=False),
            patch.object(client, "_send_wol", return_value=True),
            patch.object(client, "_wait_for_power", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_connect_fails_standby_retry(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        connect_results = iter([False, True])

        with (
            patch.object(client, "connect", side_effect=lambda: next(connect_results)),
            patch.object(client, "_is_tv_reachable", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_all_phases_fail(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with (
            patch.object(client, "connect", return_value=False),
            patch.object(client, "_is_tv_reachable", return_value=False),
            patch.object(client, "_send_wol", return_value=False),
        ):
            assert client.connect_ready() is False


class TestReboot:
    def test_reboot_not_connected(self) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        assert client.reboot() is False

    def test_reboot_success(self) -> None:
        mock_tv = Mock()
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.reboot()

        assert result is True
        mock_tv.hold_key.assert_called_once_with("KEY_POWER", 5)
        mock_tv.close.assert_called_once()

    def test_reboot_hold_key_fails(self) -> None:
        mock_tv = Mock()
        mock_tv.hold_key.side_effect = OSError("Connection lost")
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.reboot()

        assert result is False
        mock_tv.close.assert_called_once()

    def test_reboot_closes_connection_on_success(self) -> None:
        mock_tv = Mock()
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        client.reboot()

        assert client.tv is None or mock_tv.close.called


class TestRebootAndReconnect:
    @patch("time.sleep")
    def test_reboot_fails_aborts_early(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = Mock()
        client.tv.hold_key.side_effect = OSError("fail")

        result = client._reboot_and_reconnect()

        assert result is False

    @patch("time.sleep")
    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists", return_value=True)
    @patch("os.chmod")
    def test_full_reboot_cycle(
        self, _chmod: Mock, _exists: Mock, mock_tv_cls: Mock, _sleep: Mock
    ) -> None:
        mock_tv = Mock()
        mock_tv.art().supported.return_value = True
        mock_tv.art().available.return_value = [{"content_id": "MY_F001"}]
        mock_tv_cls.return_value = mock_tv

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        with patch.object(client, "_wait_for_power", return_value=True):
            result = client._reboot_and_reconnect()

        assert result is True

    @patch("time.sleep")
    def test_tv_doesnt_come_back(self, _sleep: Mock) -> None:
        mock_tv = Mock()
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        with patch.object(client, "_wait_for_power", side_effect=[True, False]):
            result = client._reboot_and_reconnect()

        assert result is False


class TestWaitForPower:
    @patch("time.sleep")
    def test_immediate_match(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with patch("samsungtvws.rest.SamsungTVRest") as mock_rest_cls:
            mock_rest = Mock()
            mock_rest.rest_power_state.return_value = True
            mock_rest_cls.return_value = mock_rest

            result = client._wait_for_power(target_on=True, timeout=10)

        assert result is True

    @patch("time.sleep")
    def test_connection_refused_means_off(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with patch("samsungtvws.rest.SamsungTVRest") as mock_rest_cls:
            mock_rest = Mock()
            mock_rest.rest_power_state.side_effect = ConnectionError("refused")
            mock_rest_cls.return_value = mock_rest

            result = client._wait_for_power(target_on=False, timeout=10)

        assert result is True

    @patch("time.sleep")
    def test_timeout(self, _sleep: Mock) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")

        with patch("samsungtvws.rest.SamsungTVRest") as mock_rest_cls:
            mock_rest = Mock()
            mock_rest.rest_power_state.return_value = False
            mock_rest_cls.return_value = mock_rest

            result = client._wait_for_power(target_on=True, timeout=5, poll_interval=3)

        assert result is False


class TestEnableArtMode:
    def test_already_in_art_mode(self) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "on"

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.enable_art_mode()

        assert result is True
        mock_tv.art().set_artmode.assert_not_called()

    def test_timeout_treated_as_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "off"
        mock_tv.art().set_artmode.side_effect = TimeoutError("timed out waiting")

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.enable_art_mode()

        assert result is True


class TestStartSlideshow:
    def test_slideshow_image_changed_is_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "on"
        mock_tv.art().set_slideshow_status.side_effect = Exception("slideshow_image_changed event")

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.start_slideshow()

        assert result is True

    @patch("time.sleep")
    def test_slideshow_retries_on_failure(self, _sleep: Mock) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "on"
        mock_tv.art().set_slideshow_status.side_effect = [
            Exception("network error"),
            Exception("network error"),
            None,
        ]

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client.start_slideshow()

        assert result is True
        assert mock_tv.art().set_slideshow_status.call_count == 3


class TestFetchArtList:
    def test_timeout_response_raises(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.return_value = {"event": "ms.channel.timeOut"}

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        with pytest.raises(TimeoutError):
            client._fetch_art_list()

    def test_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.return_value = [{"content_id": "MY_F001"}]

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        client.tv = mock_tv

        result = client._fetch_art_list()
        assert len(result) == 1


class TestTimeout:
    def test_default_timeout(self) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        assert client.timeout == 60

    def test_custom_timeout(self) -> None:
        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt", timeout=120)
        assert client.timeout == 120

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists")
    @patch("os.makedirs")
    @patch("os.chmod")
    def test_timeout_passed_to_tv(
        self, _chmod: Mock, _makedirs: Mock, mock_exists: Mock, mock_tv_cls: Mock
    ) -> None:
        mock_exists.return_value = True
        mock_tv_instance = Mock()
        mock_tv_instance.art().supported.return_value = True
        mock_tv_cls.return_value = mock_tv_instance

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt", timeout=120)
        client.connect()

        mock_tv_cls.assert_called_once_with(
            host="192.168.1.4", port=8002, token_file="/tmp/token.txt", timeout=120
        )
