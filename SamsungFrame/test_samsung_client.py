"""Tests for Samsung Frame TV client."""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch
from PIL import Image

from lib import Constants
from SamsungFrame.samsung_client import (
    SamsungFrameClient,
)


class TestSamsungFrameClient:
    """Test Samsung Frame TV client."""

    @patch.object(Constants, "SAMSUNG_FRAME_IP", "192.168.1.4")
    @patch.object(Constants, "SAMSUNG_FRAME_PORT", 8002)
    @patch.object(Constants, "SAMSUNG_FRAME_TOKEN_FILE", "/tmp/token.txt")
    def test_init_with_constants(self) -> None:
        """Test initialization with Constants."""
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

    @patch.object(Constants, "SAMSUNG_FRAME_IP", None)
    def test_init_missing_host(self) -> None:
        """Test initialization fails without host."""
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
        mock_chmod: Mock,
        _mock_makedirs: Mock,
        mock_exists: Mock,
        mock_tv: Mock,
    ) -> None:
        """Test successful connection to TV."""
        mock_exists.return_value = True
        mock_tv_instance = Mock()
        mock_tv_instance.art().supported.return_value = True
        mock_tv_instance._get_token.return_value = "test-token-123"
        mock_tv.return_value = mock_tv_instance

        client = SamsungFrameClient(host="192.168.1.4", token_file="/tmp/token.txt")
        result = client.connect()

        assert result is True
        assert client.tv is not None
        mock_tv.assert_called_once()
        mock_open.assert_called_once_with("/tmp/token.txt", "w")
        assert mock_chmod.call_count >= 1
        mock_chmod.assert_any_call("/tmp/token.txt", 0o600)

    @patch("SamsungFrame.samsung_client.SamsungTVWS")
    @patch("os.path.exists")
    @patch("os.chmod")
    @patch("time.sleep")
    @patch("builtins.open", create=True)
    def test_connect_with_retry(
        self,
        mock_open: Mock,
        mock_sleep: Mock,
        mock_chmod: Mock,
        mock_exists: Mock,
        mock_tv: Mock,
    ) -> None:
        """Test connection retry logic on failure."""
        mock_exists.return_value = True

        mock_tv_instance_fail = Mock()
        mock_tv_instance_fail.art().supported.side_effect = ConnectionError("Connection failed")

        mock_tv_instance_success = Mock()
        mock_tv_instance_success.art().supported.return_value = True
        mock_tv_instance_success._get_token.return_value = "test-token-456"

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

    @patch.object(Constants, "SAMSUNG_FRAME_SUPPORTED_FORMATS", ["jpg", "jpeg", "png"])
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

    @patch.object(Constants, "SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB", 1)
    @patch.object(Constants, "SAMSUNG_FRAME_SUPPORTED_FORMATS", ["jpg", "jpeg", "png"])
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

    @patch.object(Constants, "SAMSUNG_FRAME_SUPPORTED_FORMATS", ["jpg", "jpeg", "png"])
    @patch.object(Constants, "SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB", 10)
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
    @patch.object(Constants, "SAMSUNG_FRAME_DEFAULT_MATTE", "shadowbox_black")
    @patch.object(Constants, "SAMSUNG_FRAME_SUPPORTED_FORMATS", ["jpg", "jpeg", "png"])
    @patch.object(Constants, "SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB", 10)
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
    @patch.object(Constants, "SAMSUNG_FRAME_DEFAULT_MATTE", "shadowbox_black")
    @patch.object(Constants, "SAMSUNG_FRAME_SUPPORTED_FORMATS", ["jpg", "jpeg", "png"])
    @patch.object(Constants, "SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB", 10)
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
    @patch.object(Constants, "SAMSUNG_FRAME_DEFAULT_MATTE", "shadowbox_black")
    @patch.object(Constants, "SAMSUNG_FRAME_SUPPORTED_FORMATS", ["jpg", "jpeg", "png"])
    @patch.object(Constants, "SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB", 10)
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
        """Test successful art mode enable."""
        mock_tv_instance = Mock()
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
