"""Tests for Samsung Frame TV client."""

import os
import socket
import tempfile

import pytest
from PIL import Image
from unittest.mock import Mock, patch, MagicMock

from SamsungFrame.samsung_client import SamsungFrameClient

TV_HOST = "192.168.1.4"
TOKEN_FILE = "/tmp/token.txt"


def make_client(**kwargs: object) -> SamsungFrameClient:
    kwargs.setdefault("host", TV_HOST)
    kwargs.setdefault("token_file", TOKEN_FILE)
    return SamsungFrameClient(**kwargs)  # type: ignore[arg-type]


class TestSamsungFrameClient:
    def test_init_with_config(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.ip = TV_HOST
        mock_cfg.samsung_frame.port = 8002
        mock_cfg.samsung_frame.token_file = TOKEN_FILE

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            client = SamsungFrameClient()
            assert client.host == TV_HOST
            assert client.port == 8002

    def test_init_missing_host(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.ip = ""
        mock_cfg.samsung_frame.port = 8002
        mock_cfg.samsung_frame.token_file = TOKEN_FILE

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            with pytest.raises(ValueError, match="Samsung Frame TV IP address required"):
                SamsungFrameClient()

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists", return_value=True)
    @patch("os.chmod")
    def test_connect_success(self, _chmod: Mock, _exists: Mock, mock_tv: Mock) -> None:
        mock_tv_instance = Mock()
        mock_tv_instance.art().supported.return_value = True
        mock_tv.return_value = mock_tv_instance

        client = make_client()
        assert client.connect() is True
        assert client.tv is not None

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists", return_value=True)
    @patch("os.chmod")
    @patch("time.sleep")
    def test_connect_with_retry(
        self, mock_sleep: Mock, _chmod: Mock, _exists: Mock, mock_tv: Mock
    ) -> None:
        fail = Mock()
        fail.art().supported.side_effect = ConnectionError("fail")
        success = Mock()
        success.art().supported.return_value = True
        mock_tv.side_effect = [fail, fail, success]

        client = make_client()
        assert client.connect() is True
        assert mock_tv.call_count == 3

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists", return_value=True)
    @patch("time.sleep")
    def test_connect_max_retries(self, _sleep: Mock, _exists: Mock, mock_tv: Mock) -> None:
        mock_tv_instance = Mock()
        mock_tv_instance.art().supported.side_effect = ConnectionError("fail")
        mock_tv.return_value = mock_tv_instance

        client = make_client()
        assert client.connect() is False
        assert mock_tv.call_count == 3

    def test_validate_image_file_invalid_format(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"test")
            path = f.name
        try:
            assert make_client().validate_image_file(path) is False
        finally:
            os.unlink(path)

    def test_validate_image_file_success(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            Image.new("RGB", (100, 100), color="red").save(f, format="JPEG")
            path = f.name
        try:
            assert make_client().validate_image_file(path) is True
        finally:
            os.unlink(path)

    def test_upload_image_success(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            Image.new("RGB", (100, 100), color="blue").save(f, format="JPEG")
            path = f.name
        try:
            mock_tv = Mock()
            mock_tv.art().upload.return_value = "image123"
            client = make_client()
            client.tv = mock_tv
            assert client.upload_image(path) == "image123"
        finally:
            os.unlink(path)

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_upload_images_from_folder_success(self, mock_tv_cls: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(3):
                Image.new("RGB", (100, 100)).save(
                    os.path.join(tmp_dir, f"img{i}.jpg"), format="JPEG"
                )

            mock_tv = Mock()
            mock_tv.art().upload.side_effect = ["id1", "id2", "id3"]
            client = make_client()
            client.tv = mock_tv

            summary = client.upload_images_from_folder(tmp_dir)
            assert summary.successful_uploads == 3
            assert summary.failed_uploads == 0

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    def test_upload_images_partial_failure(self, mock_tv_cls: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(2):
                Image.new("RGB", (100, 100)).save(
                    os.path.join(tmp_dir, f"img{i}.jpg"), format="JPEG"
                )
            with open(os.path.join(tmp_dir, "bad.jpg"), "w") as f:
                f.write("not an image")

            mock_tv = Mock()
            mock_tv.art().upload.side_effect = ["id1", "id2"]
            client = make_client()
            client.tv = mock_tv

            summary = client.upload_images_from_folder(tmp_dir)
            assert summary.successful_uploads == 2
            assert summary.failed_uploads == 1

    def test_enable_art_mode_already_on(self) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "on"
        client = make_client()
        client.tv = mock_tv

        assert client.enable_art_mode() is True
        mock_tv.art().set_artmode.assert_not_called()

    def test_enable_art_mode_timeout_is_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "off"
        mock_tv.art().set_artmode.side_effect = TimeoutError("timed out")
        client = make_client()
        client.tv = mock_tv

        assert client.enable_art_mode() is True

    @patch("time.sleep")
    def test_cycle_images_filters_user_photos(self, mock_sleep: Mock) -> None:
        mock_tv = Mock()
        mock_tv.art().available.return_value = [
            {"content_id": "MY_F0001"},
            {"content_id": "MY_F0002"},
            {"content_id": "ART_12345"},
        ]
        mock_tv.art().set_artmode.return_value = None
        mock_sleep.side_effect = [None, KeyboardInterrupt()]

        client = make_client()
        client.tv = mock_tv
        client.cycle_images(period=15, user_photos_only=True)

        assert mock_tv.art().select_image.call_count == 2
        mock_tv.art().select_image.assert_any_call("MY_F0001")
        mock_tv.art().select_image.assert_any_call("MY_F0002")


class TestPing:
    def test_not_connected_raises(self) -> None:
        with pytest.raises(RuntimeError, match="Not connected"):
            make_client().ping()

    def test_failure_propagates(self) -> None:
        mock_tv = Mock()
        mock_tv.art().supported.side_effect = TimeoutError("timeout")
        client = make_client()
        client.tv = mock_tv

        with pytest.raises(TimeoutError):
            client.ping()


class TestGetAvailableArtStrict:
    def test_not_connected_raises(self) -> None:
        with pytest.raises(RuntimeError):
            make_client().get_available_art_strict()

    def test_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.return_value = [{"content_id": "MY_F001"}]
        client = make_client()
        client.tv = mock_tv

        result = client.get_available_art_strict()
        assert len(result) == 1

    def test_timeout_response_raises(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.return_value = {"event": "ms.channel.timeOut"}
        client = make_client()
        client.tv = mock_tv

        with pytest.raises(TimeoutError):
            client.get_available_art_strict()

    def test_lenient_returns_empty_on_error(self) -> None:
        mock_tv = Mock()
        mock_tv.art().available.side_effect = ConnectionError("closed")
        client = make_client()
        client.tv = mock_tv

        assert client.get_available_art() == []


class TestReconnectDuringUpload:
    @patch("time.sleep")
    def test_stops_after_reconnect_fails(self, _sleep: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(5):
                Image.new("RGB", (100, 100)).save(
                    os.path.join(tmp_dir, f"img_{i}.jpg"), format="JPEG"
                )

            mock_tv = Mock()
            mock_tv.art().upload.return_value = None
            client = make_client()
            client.tv = mock_tv

            with (
                patch.object(client, "_reconnect", return_value=False),
                patch.object(client, "ensure_art_mode", return_value=False),
                patch.object(client, "_reboot_and_reconnect", return_value=False),
            ):
                summary = client.upload_images_from_folder(tmp_dir, max_consecutive_failures=3)

            assert summary.successful_uploads == 0

    @patch("time.sleep")
    def test_only_one_reboot_per_batch(self, _sleep: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(8):
                Image.new("RGB", (100, 100)).save(
                    os.path.join(tmp_dir, f"img_{i}.jpg"), format="JPEG"
                )

            mock_tv = Mock()
            mock_tv.art().upload.return_value = None
            client = make_client()
            client.tv = mock_tv

            reboot_mock = Mock(return_value=False)
            with (
                patch.object(client, "ensure_art_mode", return_value=False),
                patch.object(client, "_reboot_and_reconnect", reboot_mock),
            ):
                client.upload_images_from_folder(tmp_dir, max_consecutive_failures=3)

            reboot_mock.assert_called_once()


class TestSendWol:
    def test_no_mac_returns_false(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.mac = ""
        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            assert make_client()._send_wol() is False

    @patch("SamsungFrame.samsung_client.time")
    @patch("SamsungFrame.samsung_client.socket")
    def test_multi_target_packets(self, mock_socket_mod: Mock, _time: Mock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.mac = "AA:BB:CC:DD:EE:FF"
        mock_cfg.samsung_frame.wol_password = ""
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = Mock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = Mock(return_value=False)
        mock_socket_mod.AF_INET = socket.AF_INET
        mock_socket_mod.SOCK_DGRAM = socket.SOCK_DGRAM
        mock_socket_mod.SOL_SOCKET = socket.SOL_SOCKET
        mock_socket_mod.SO_BROADCAST = socket.SO_BROADCAST

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            assert make_client()._send_wol() is True

        assert mock_sock.sendto.call_count == 12  # 3 rounds × 4 targets
        magic = mock_sock.sendto.call_args_list[0][0][0]
        assert magic[:6] == b"\xff" * 6
        assert len(magic) == 102  # no SecureON

    @patch("SamsungFrame.samsung_client.time")
    @patch("SamsungFrame.samsung_client.socket")
    def test_secureon_appends_password(self, mock_socket_mod: Mock, _time: Mock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.mac = "AA:BB:CC:DD:EE:FF"
        mock_cfg.samsung_frame.wol_password = "11:22:33:44:55:66"
        mock_sock = MagicMock()
        mock_socket_mod.socket.return_value.__enter__ = Mock(return_value=mock_sock)
        mock_socket_mod.socket.return_value.__exit__ = Mock(return_value=False)
        mock_socket_mod.AF_INET = socket.AF_INET
        mock_socket_mod.SOCK_DGRAM = socket.SOCK_DGRAM
        mock_socket_mod.SOL_SOCKET = socket.SOL_SOCKET
        mock_socket_mod.SO_BROADCAST = socket.SO_BROADCAST

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            assert make_client()._send_wol() is True

        magic = mock_sock.sendto.call_args_list[0][0][0]
        assert len(magic) == 108  # 102 + 6 SecureON


class TestSmartThingsPowerOn:
    def test_no_config_returns_false(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.smartthings_token = ""
        mock_cfg.samsung_frame.smartthings_device_id = ""
        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            assert make_client()._smartthings_power_on() is False

    @patch("requests.post")
    def test_success(self, mock_post: Mock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.smartthings_token = "test-token"
        mock_cfg.samsung_frame.smartthings_device_id = "device-123"
        mock_post.return_value = Mock(ok=True)

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            assert make_client()._smartthings_power_on() is True

        assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer test-token"

    @patch("requests.post")
    def test_api_error(self, mock_post: Mock) -> None:
        mock_cfg = MagicMock()
        mock_cfg.samsung_frame.smartthings_token = "test-token"
        mock_cfg.samsung_frame.smartthings_device_id = "device-123"
        mock_post.return_value = Mock(ok=False, status_code=403, text="Forbidden")

        with patch("SamsungFrame.samsung_client.cfg", mock_cfg):
            assert make_client()._smartthings_power_on() is False


class TestContextManager:
    def test_enter_calls_connect_ready_and_exit_closes(self) -> None:
        client = make_client()
        with (
            patch.object(client, "connect_ready", return_value=True) as mock_cr,
            patch.object(client, "close") as mock_close,
        ):
            with client as c:
                assert c is client
                mock_cr.assert_called_once()
            mock_close.assert_called_once()

    def test_enter_raises_on_failure(self) -> None:
        client = make_client()
        with patch.object(client, "connect_ready", return_value=False):
            with pytest.raises(ConnectionError):
                client.__enter__()

    def test_exit_closes_on_exception(self) -> None:
        client = make_client()
        with (
            patch.object(client, "connect_ready", return_value=True),
            patch.object(client, "close") as mock_close,
        ):
            try:
                with client:
                    raise ValueError("boom")
            except ValueError:
                pass
            mock_close.assert_called_once()


class TestConnectReady:
    @patch("time.sleep")
    def test_already_connected(self, _sleep: Mock) -> None:
        client = make_client()
        with (
            patch.object(client, "_send_wol"),
            patch.object(client, "_smartthings_power_on"),
            patch.object(client, "connect", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_art_fails_triggers_reboot(self, _sleep: Mock) -> None:
        client = make_client()
        with (
            patch.object(client, "_send_wol"),
            patch.object(client, "_smartthings_power_on"),
            patch.object(client, "connect", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=False),
            patch.object(client, "_reboot_and_reconnect", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_wol_wakes_tv(self, _sleep: Mock) -> None:
        client = make_client()
        connect_results = iter([False, True])

        with (
            patch.object(client, "_send_wol", return_value=True),
            patch.object(client, "_smartthings_power_on"),
            patch.object(client, "connect", side_effect=lambda: next(connect_results)),
            patch.object(client, "_is_tv_reachable", return_value=False),
            patch.object(client, "_wait_for_power", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_standby_retry(self, _sleep: Mock) -> None:
        client = make_client()
        connect_results = iter([False, True])

        with (
            patch.object(client, "_send_wol"),
            patch.object(client, "_smartthings_power_on"),
            patch.object(client, "connect", side_effect=lambda: next(connect_results)),
            patch.object(client, "_is_tv_reachable", return_value=True),
            patch.object(client, "ensure_art_mode", return_value=True),
        ):
            assert client.connect_ready() is True

    @patch("time.sleep")
    def test_all_phases_fail(self, _sleep: Mock) -> None:
        client = make_client()
        with (
            patch.object(client, "_send_wol"),
            patch.object(client, "_smartthings_power_on"),
            patch.object(client, "connect", return_value=False),
            patch.object(client, "_is_tv_reachable", return_value=False),
            patch.object(client, "_wait_for_power", return_value=False),
        ):
            assert client.connect_ready() is False

    @patch("time.sleep")
    def test_wol_fires_before_connect(self, _sleep: Mock) -> None:
        client = make_client()
        call_order: list[str] = []

        def _track_connect() -> bool:
            call_order.append("connect")
            return True

        with (
            patch.object(client, "_send_wol", side_effect=lambda: call_order.append("wol")),
            patch.object(
                client, "_smartthings_power_on", side_effect=lambda: call_order.append("st")
            ),
            patch.object(client, "connect", side_effect=_track_connect),
            patch.object(client, "ensure_art_mode", return_value=True),
        ):
            assert client.connect_ready() is True

        assert call_order[:2] == ["wol", "st"]
        assert call_order[2] == "connect"


class TestReboot:
    def test_not_connected(self) -> None:
        assert make_client().reboot() is False

    def test_success(self) -> None:
        mock_tv = Mock()
        client = make_client()
        client.tv = mock_tv

        assert client.reboot() is True
        mock_tv.hold_key.assert_called_once_with("KEY_POWER", 5)
        mock_tv.close.assert_called_once()

    def test_exception_during_hold_is_success(self) -> None:
        mock_tv = Mock()
        mock_tv.hold_key.side_effect = OSError("Connection lost")
        client = make_client()
        client.tv = mock_tv

        assert client.reboot() is True
        mock_tv.close.assert_called_once()


class TestRebootAndReconnect:
    @patch("time.sleep")
    def test_wol_fallback_fails(self, _sleep: Mock) -> None:
        client = make_client()
        with patch.object(client, "_send_wol", return_value=False):
            assert client._reboot_and_reconnect() is False

    @patch("time.sleep")
    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists", return_value=True)
    @patch("os.chmod")
    def test_wol_fallback_succeeds(
        self, _chmod: Mock, _exists: Mock, mock_tv_cls: Mock, _sleep: Mock
    ) -> None:
        mock_tv = Mock()
        mock_tv.art().supported.return_value = True
        mock_tv.art().available.return_value = [{"content_id": "MY_F001"}]
        mock_tv_cls.return_value = mock_tv

        client = make_client()
        with (
            patch.object(client, "_send_wol", return_value=True),
            patch.object(client, "_wait_for_power", return_value=True),
        ):
            assert client._reboot_and_reconnect() is True

    @patch("time.sleep")
    def test_tv_doesnt_come_back(self, _sleep: Mock) -> None:
        mock_tv = Mock()
        client = make_client()
        client.tv = mock_tv

        with patch.object(client, "_wait_for_power", side_effect=[True, False]):
            assert client._reboot_and_reconnect() is False


class TestWaitForPower:
    @patch("time.sleep")
    def test_immediate_match(self, _sleep: Mock) -> None:
        client = make_client()
        with patch("samsungtvws.rest.SamsungTVRest") as mock_rest_cls:
            mock_rest_cls.return_value = Mock(rest_power_state=Mock(return_value=True))
            assert client._wait_for_power(target_on=True, timeout=10) is True

    @patch("time.sleep")
    def test_connection_refused_means_off(self, _sleep: Mock) -> None:
        client = make_client()
        with patch("samsungtvws.rest.SamsungTVRest") as mock_rest_cls:
            mock_rest_cls.return_value = Mock(
                rest_power_state=Mock(side_effect=ConnectionError("refused"))
            )
            assert client._wait_for_power(target_on=False, timeout=10) is True

    @patch("time.sleep")
    def test_timeout(self, _sleep: Mock) -> None:
        client = make_client()
        with patch("samsungtvws.rest.SamsungTVRest") as mock_rest_cls:
            mock_rest_cls.return_value = Mock(rest_power_state=Mock(return_value=False))
            assert client._wait_for_power(target_on=True, timeout=5, poll_interval=3) is False


class TestStartSlideshow:
    def test_slideshow_image_changed_is_success(self) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "on"
        mock_tv.art().set_slideshow_status.side_effect = Exception("slideshow_image_changed event")
        client = make_client()
        client.tv = mock_tv

        assert client.start_slideshow() is True

    @patch("time.sleep")
    def test_retries_on_failure(self, _sleep: Mock) -> None:
        mock_tv = Mock()
        mock_tv.art().get_artmode.return_value = "on"
        mock_tv.art().set_slideshow_status.side_effect = [
            Exception("network error"),
            Exception("network error"),
            None,
        ]
        client = make_client()
        client.tv = mock_tv

        assert client.start_slideshow() is True
        assert mock_tv.art().set_slideshow_status.call_count == 3


class TestTimeout:
    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists", return_value=True)
    @patch("os.chmod")
    def test_timeout_passed_to_tv(
        self, _chmod: Mock, _exists: Mock, mock_tv_cls: Mock
    ) -> None:
        mock_tv_cls.return_value = Mock(art=Mock(return_value=Mock(supported=Mock(return_value=True))))

        client = make_client(timeout=120)
        client.connect()

        mock_tv_cls.assert_called_once_with(
            host=TV_HOST, port=8002, token_file=TOKEN_FILE, timeout=120
        )
