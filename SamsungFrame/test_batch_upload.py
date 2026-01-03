"""Tests for Samsung Frame TV batch upload."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from PIL import Image

from SamsungFrame.batch_upload import (
    ImageConverter,
    discover_images,
    delete_all_art,
)
from SamsungFrame.samsung_client import SamsungFrameClient


class TestImageDiscovery:
    """Test image discovery and filtering."""

    def test_discover_empty_directory(self) -> None:
        """Test discovery in empty directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            images = discover_images(tmp_dir)
            assert len(images) == 0

    def test_discover_nonexistent_directory(self) -> None:
        """Test discovery fails for non-existent directory."""
        with pytest.raises(ValueError, match="Directory not found"):
            discover_images("/nonexistent/directory")

    def test_discover_jpg_files(self) -> None:
        """Test discovery finds JPG files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create test JPG files
            for i in range(3):
                img = Image.new("RGB", (100, 100), color="red")
                img_path = Path(tmp_dir) / f"test_{i}.jpg"
                img.save(img_path, format="JPEG")

            images = discover_images(tmp_dir, min_size_mb=0.0)
            assert len(images) == 3
            assert all(img.suffix == ".jpg" for img in images)

    def test_discover_mixed_formats(self) -> None:
        """Test discovery finds JPG, PNG, HEIC."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create various formats
            formats = [("test1.jpg", "JPEG"), ("test2.png", "PNG"), ("test3.JPG", "JPEG")]
            for filename, fmt in formats:
                img = Image.new("RGB", (100, 100), color="blue")
                img_path = Path(tmp_dir) / filename
                img.save(img_path, format=fmt)

            # Create HEIC placeholder (can't create real HEIC easily)
            heic_path = Path(tmp_dir) / "test4.heic"
            heic_path.write_bytes(b"fake heic content" * 1000)  # Make it > 1MB

            images = discover_images(tmp_dir, min_size_mb=0.0)
            assert len(images) == 4

    def test_discover_filter_small_files(self) -> None:
        """Test filtering files below minimum size."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create small file
            small_img = Image.new("RGB", (10, 10), color="green")
            small_path = Path(tmp_dir) / "small.jpg"
            small_img.save(small_path, format="JPEG")

            # Create large file (ensure >0.1MB by saving at high quality)
            large_img = Image.new("RGB", (3000, 3000), color="red")
            large_path = Path(tmp_dir) / "large.jpg"
            large_img.save(large_path, format="JPEG", quality=95)

            # Verify sizes
            small_size_mb = small_path.stat().st_size / (1024 * 1024)
            large_size_mb = large_path.stat().st_size / (1024 * 1024)
            assert small_size_mb < 0.1
            assert large_size_mb > 0.1

            images = discover_images(tmp_dir, min_size_mb=0.1)
            assert len(images) == 1
            assert images[0].name == "large.jpg"

    def test_discover_filter_thumbnails(self) -> None:
        """Test filtering thumbnail patterns."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create normal files
            for name in ["photo1.jpg", "photo2.jpg"]:
                img = Image.new("RGB", (500, 500), color="blue")
                img.save(Path(tmp_dir) / name, format="JPEG")

            # Create thumbnails (should be filtered)
            thumbnail_names = [
                "photo1_thumb.jpg",
                "photo2_thumbnail.jpg",
                "photo3_small.jpg",
                "photo4_small@2x.jpg",
                "photo5_thumbnail@3x.png",
                "photo6_small@10x.jpg",
                "photo7_thumb@100x.png",
            ]
            for name in thumbnail_names:
                img = Image.new("RGB", (500, 500), color="red")
                ext = "PNG" if name.endswith(".png") else "JPEG"
                img.save(Path(tmp_dir) / name, format=ext)

            images = discover_images(tmp_dir, min_size_mb=0.0)
            assert len(images) == 2
            assert all("thumb" not in img.name for img in images)
            assert all("thumbnail" not in img.name for img in images)
            assert all("small" not in img.name for img in images)

    def test_discover_recursive(self) -> None:
        """Test recursive directory traversal."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            # Create nested structure
            (root / "subdir1").mkdir()
            (root / "subdir1" / "subdir2").mkdir()

            # Add images at different levels
            for path in [root, root / "subdir1", root / "subdir1" / "subdir2"]:
                img = Image.new("RGB", (100, 100), color="purple")
                img.save(path / "test.jpg", format="JPEG")

            images = discover_images(tmp_dir, min_size_mb=0.0)
            assert len(images) == 3


class TestImageConverter:
    """Test HEIC conversion and resizing."""

    def test_jpg_passthrough(self) -> None:
        """Test JPG files pass through unchanged."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create JPG
            img = Image.new("RGB", (500, 500), color="yellow")
            jpg_path = Path(tmp_dir) / "test.jpg"
            img.save(jpg_path, format="JPEG")

            converter = ImageConverter(tmp_dir)
            result = converter.convert_if_needed(jpg_path)

            assert result.success
            assert result.converted_path is None
            assert result.source_path == str(jpg_path)

    def test_png_passthrough(self) -> None:
        """Test PNG files pass through unchanged."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create PNG
            img = Image.new("RGB", (500, 500), color="cyan")
            png_path = Path(tmp_dir) / "test.png"
            img.save(png_path, format="PNG")

            converter = ImageConverter(tmp_dir)
            result = converter.convert_if_needed(png_path)

            assert result.success
            assert result.converted_path is None

    def test_resize_large_image(self) -> None:
        """Test resizing image larger than 4K."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create oversized image
            img = Image.new("RGB", (5000, 4000), color="orange")
            img_path = Path(tmp_dir) / "large.jpg"
            img.save(img_path, format="JPEG")

            converter = ImageConverter(tmp_dir)
            # Manually test resize method
            resized = converter._resize_if_needed(img)

            assert resized.width <= 3840
            assert resized.height <= 2160

    def test_resize_maintains_aspect_ratio(self) -> None:
        """Test resizing maintains aspect ratio."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create 16:9 image
            img = Image.new("RGB", (4800, 2700), color="magenta")  # 16:9
            img_path = Path(tmp_dir) / "test.jpg"
            img.save(img_path, format="JPEG")

            converter = ImageConverter(tmp_dir)
            resized = converter._resize_if_needed(img)

            # Should maintain 16:9 ratio
            ratio = resized.width / resized.height
            assert abs(ratio - (16 / 9)) < 0.01

    def test_compress_to_limit(self) -> None:
        """Test compression reduces file size."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create large image
            img = Image.new("RGB", (3840, 2160), color="blue")
            output_path = Path(tmp_dir) / "output.jpg"

            converter = ImageConverter(tmp_dir)
            success = converter._compress_to_limit(img, output_path)

            assert success
            assert output_path.exists()
            size_mb = output_path.stat().st_size / (1024 * 1024)
            assert size_mb <= 10.0

    def test_invalid_image_handling(self) -> None:
        """Test handling of invalid image files."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create invalid HEIC file
            bad_file = Path(tmp_dir) / "bad.heic"
            bad_file.write_bytes(b"not a real image")

            converter = ImageConverter(tmp_dir)
            result = converter.convert_if_needed(bad_file)

            assert not result.success
            assert result.error_message is not None


class TestArtDeletion:
    """Test art deletion functionality."""

    @patch("SamsungFrame.batch_upload.input")
    def test_delete_with_confirmation(self, mock_input: Mock) -> None:
        """Test deletion requires confirmation."""
        mock_input.return_value = "y"

        mock_tv = Mock()
        mock_tv.art().delete_list = Mock()

        client = Mock(spec=SamsungFrameClient)
        client.tv = mock_tv
        client.get_available_art.return_value = [
            {"content_id": "MY_F0001"},
            {"content_id": "MY_F0002"},
        ]

        result = delete_all_art(client, force=False)

        assert result["total"] == 2
        assert result["deleted"] == 2
        assert result["failed"] == 0
        mock_input.assert_called_once()
        mock_tv.art().delete_list.assert_called_once()

    @patch("SamsungFrame.batch_upload.input")
    def test_delete_cancelled(self, mock_input: Mock) -> None:
        """Test deletion can be cancelled."""
        mock_input.return_value = "n"

        mock_tv = Mock()
        client = Mock(spec=SamsungFrameClient)
        client.tv = mock_tv
        client.get_available_art.return_value = [{"content_id": "MY_F0001"}]

        result = delete_all_art(client, force=False)

        assert result["deleted"] == 0
        mock_tv.art().delete_list.assert_not_called()

    def test_delete_with_force(self) -> None:
        """Test force flag skips confirmation."""
        mock_tv = Mock()
        mock_tv.art().delete_list = Mock()

        client = Mock(spec=SamsungFrameClient)
        client.tv = mock_tv
        client.get_available_art.return_value = [{"content_id": "MY_F0001"}]

        result = delete_all_art(client, force=True)

        assert result["deleted"] == 1
        mock_tv.art().delete_list.assert_called_once()

    def test_delete_empty_list(self) -> None:
        """Test deletion with no art on TV."""
        mock_tv = Mock()
        client = Mock(spec=SamsungFrameClient)
        client.tv = mock_tv
        client.get_available_art.return_value = []

        result = delete_all_art(client, force=True)

        assert result["total"] == 0
        assert result["deleted"] == 0

    def test_delete_filters_user_art_only(self) -> None:
        """Test deletion only removes user-uploaded art."""
        mock_tv = Mock()
        mock_tv.art().delete_list = Mock()

        client = Mock(spec=SamsungFrameClient)
        client.tv = mock_tv
        # Mix of user art (MY_F) and Samsung art (SAM_)
        client.get_available_art.return_value = [
            {"content_id": "MY_F0001"},  # User art
            {"content_id": "SAM_0001"},  # Samsung art
            {"content_id": "MY_F0002"},  # User art
        ]

        result = delete_all_art(client, force=True)

        # Should only delete 2 user-uploaded items
        assert result["total"] == 2
        assert result["deleted"] == 2

        # Verify only MY_F items were passed to delete
        call_args = mock_tv.art().delete_list.call_args[0][0]
        assert "MY_F0001" in call_args
        assert "MY_F0002" in call_args
        assert "SAM_0001" not in call_args

    def test_delete_batch_failure_fallback(self) -> None:
        """Test fallback to individual deletes on batch failure."""
        mock_tv = Mock()
        # Batch delete fails
        mock_tv.art().delete_list.side_effect = Exception("Batch failed")
        # Individual deletes succeed
        mock_tv.art().delete = Mock()

        client = Mock(spec=SamsungFrameClient)
        client.tv = mock_tv
        client.get_available_art.return_value = [
            {"content_id": "MY_F0001"},
            {"content_id": "MY_F0002"},
        ]

        result = delete_all_art(client, force=True)

        assert result["deleted"] == 2
        assert mock_tv.art().delete.call_count == 2

    def test_delete_not_connected(self) -> None:
        """Test deletion fails when not connected."""
        client = Mock(spec=SamsungFrameClient)
        client.tv = None

        with pytest.raises(RuntimeError, match="Not connected to TV"):
            delete_all_art(client, force=True)


class TestBatchUpload:
    """Test batch upload orchestration."""

    def test_dry_run_mode(self) -> None:
        """Test dry-run mode doesn't upload."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create test image
            img = Image.new("RGB", (100, 100), color="red")
            img.save(Path(tmp_dir) / "test.jpg", format="JPEG")

            from argparse import Namespace

            args = Namespace(
                source_dir=tmp_dir,
                dry_run=True,
                delete_existing=False,
                force=False,
                notify=False,
                min_size_mb=0.0,
                matte=None,
            )

            from SamsungFrame.batch_upload import run_batch_upload

            # Should succeed without connecting to TV
            result = run_batch_upload(args)
            assert result == 0
