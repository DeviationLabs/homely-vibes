#!/usr/bin/env python3
"""Batch upload images to Samsung Frame TV with HEIC conversion."""

import argparse
import hashlib
import os
import random
import re
import shutil
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType
from typing import Any, List, Dict, Optional

import pillow_heif
from PIL import Image
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from SamsungFrame.samsung_client import SamsungFrameClient, ImageUploadSummary
from lib.MyPushover import Pushover
from lib.logger import get_logger
from lib.config import get_config

# Register HEIC support for Pillow
pillow_heif.register_heif_opener()

cfg = get_config()
logger = get_logger(__name__)
pushover = Pushover(
    cfg.pushover.user,
    cfg.pushover.tokens.get("SamsungFrame", cfg.pushover.default_token),
)

# Thumbnail patterns to exclude
THUMBNAIL_PATTERNS = re.compile(r"_(thumb|thumbnail|small)(@\d+x)?\.[\w]+$", re.IGNORECASE)

# Global state for signal handler
_current_summary: Optional["BatchUploadSummary"] = None
_notification_sent = False


def trim_filename(name: str, max_length: int = 50, seen: Optional[set[str]] = None) -> str:
    """Trim filename to max_length chars, preserving extension and handling collisions.

    Args:
        name: Original filename (e.g. "very_long_photo_name.jpg")
        max_length: Maximum total length including extension
        seen: Set of already-used names for collision detection (mutated in place)
    """
    stem = Path(name).stem
    ext = Path(name).suffix  # includes dot

    max_stem = max_length - len(ext)
    if max_stem < 1:
        max_stem = 1

    trimmed = stem[:max_stem]
    candidate = trimmed + ext

    if seen is not None:
        counter = 1
        while candidate.lower() in seen:
            suffix = f"_{counter}"
            available = max_stem - len(suffix)
            if available < 1:
                available = 1
            candidate = stem[:available] + suffix + ext
            counter += 1
        seen.add(candidate.lower())

    return candidate


def _send_interrupt_notification(_signum: int, _frame: Optional[FrameType]) -> None:
    """Signal handler to send notification on interrupt."""
    global _notification_sent
    if _current_summary and not _notification_sent:
        _notification_sent = True
        send_batch_notification(_current_summary, interrupted=True)
    sys.exit(1)


class ConversionResult(BaseModel):
    """Result of a single image conversion."""

    source_path: str
    converted_path: Optional[str] = None  # None if no conversion needed
    success: bool
    error_message: Optional[str] = None
    original_size_mb: float
    converted_size_mb: Optional[float] = None


class BatchUploadSummary(BaseModel):
    """Complete batch upload operation summary."""

    total_discovered: int
    total_filtered: int
    heic_converted: int
    conversion_failures: int
    art_deleted: int
    art_delete_failures: int
    upload_summary: ImageUploadSummary
    conversion_errors: List[Dict[str, str]]


class ImageConverter:
    """Downsize all images to 4K and under max file size; convert HEIC to JPG."""

    MAX_WIDTH = 3840
    MAX_HEIGHT = 2160
    JPG_QUALITY = 95

    def __init__(self, temp_dir: str):
        self.temp_dir = Path(temp_dir)
        self.logger = get_logger(f"{__name__}.ImageConverter")
        cfg = get_config()
        self.max_size_mb = cfg.samsung_frame.max_image_size_mb

    def convert_if_needed(self, image_path: Path) -> ConversionResult:
        """Downsize to 4K and compress under max_image_size_mb. Convert HEIC to JPG."""
        original_size_mb = image_path.stat().st_size / (1024 * 1024)
        ext = image_path.suffix.lower()

        try:
            with Image.open(image_path) as raw_img:
                img: Image.Image = raw_img
                width, height = img.size
                needs_resize = width > self.MAX_WIDTH or height > self.MAX_HEIGHT
                needs_compress = original_size_mb > self.max_size_mb
                is_heic = ext == ".heic"

                if not needs_resize and not needs_compress and not is_heic:
                    return ConversionResult(
                        source_path=str(image_path),
                        converted_path=None,
                        success=True,
                        original_size_mb=original_size_mb,
                        converted_size_mb=None,
                    )

                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                if needs_resize:
                    img = self._resize_if_needed(img)

                path_hash = hashlib.md5(str(image_path).encode()).hexdigest()[:8]
                out_ext = "jpg" if is_heic else ext.lstrip(".")
                if out_ext == "jpeg":
                    out_ext = "jpg"
                output_path = self.temp_dir / f"{image_path.stem}_{path_hash}.{out_ext}"

                if out_ext == "png" and not needs_compress:
                    img.save(output_path, format="PNG", optimize=True)
                else:
                    if out_ext == "png":
                        out_ext = "jpg"
                        output_path = output_path.with_suffix(".jpg")
                    success = self._compress_to_limit(img, output_path)
                    if not success:
                        return ConversionResult(
                            source_path=str(image_path),
                            success=False,
                            error_message=f"Could not compress below {self.max_size_mb}MB",
                            original_size_mb=original_size_mb,
                        )

                converted_size_mb = output_path.stat().st_size / (1024 * 1024)
                self.logger.debug(
                    f"Converted {image_path.name}: "
                    f"{original_size_mb:.2f}MB → {converted_size_mb:.2f}MB"
                )

                return ConversionResult(
                    source_path=str(image_path),
                    converted_path=str(output_path),
                    success=True,
                    original_size_mb=original_size_mb,
                    converted_size_mb=converted_size_mb,
                )

        except Exception as e:
            self.logger.error(f"Error converting {image_path.name}: {e}")
            return ConversionResult(
                source_path=str(image_path),
                success=False,
                error_message=str(e),
                original_size_mb=original_size_mb,
            )

    def _resize_if_needed(self, img: Image.Image) -> Image.Image:
        """Resize image if it exceeds 4K while maintaining aspect ratio."""
        width, height = img.size

        if width <= self.MAX_WIDTH and height <= self.MAX_HEIGHT:
            return img

        # Calculate aspect ratio preserving dimensions
        ratio = min(self.MAX_WIDTH / width, self.MAX_HEIGHT / height)
        new_width = int(width * ratio)
        new_height = int(height * ratio)

        self.logger.debug(f"Resizing from {width}×{height} to {new_width}×{new_height}")
        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    def _compress_to_limit(self, img: Image.Image, output_path: Path) -> bool:
        """Save with decreasing quality until under max_size_mb."""
        for quality in range(self.JPG_QUALITY, 69, -5):  # 95, 90, 85, 80, 75, 70
            img.save(output_path, format="JPEG", quality=quality, optimize=True)
            size_mb = output_path.stat().st_size / (1024 * 1024)

            if size_mb <= self.max_size_mb:
                if quality < self.JPG_QUALITY:
                    self.logger.info(f"Compressed to quality {quality} ({size_mb:.2f}MB)")
                return True

        return False


def discover_images(root_dir: str, min_size_mb: float = 1.0) -> List[Path]:
    """Recursively find images, filter thumbnails.

    Args:
        root_dir: Directory to search
        min_size_mb: Minimum file size in MB (default 1.0)

    Returns:
        Sorted list of Path objects for valid images
    """
    root = Path(root_dir)
    if not root.is_dir():
        raise ValueError(f"Directory not found: {root_dir}")

    valid_extensions = {".heic", ".jpg", ".jpeg", ".png"}
    min_size_bytes = min_size_mb * 1024 * 1024
    images = []

    logger.info(f"Scanning {root_dir} recursively (min size: {min_size_mb}MB)...")

    for path in root.rglob("*"):
        # Skip non-files
        if not path.is_file():
            continue

        # Check extension
        ext = path.suffix.lower()
        if ext not in valid_extensions:
            continue

        # Check file size
        try:
            if path.stat().st_size < min_size_bytes:
                logger.debug(f"Skipping small file: {path.name}")
                continue
        except OSError as e:
            logger.warning(f"Could not stat {path.name}: {e}")
            continue

        # Check thumbnail patterns
        if THUMBNAIL_PATTERNS.search(path.name):
            logger.debug(f"Skipping thumbnail: {path.name}")
            continue

        images.append(path)

    logger.info(f"Found {len(images)} valid images")
    return sorted(images)


def delete_all_art(client: SamsungFrameClient, force: bool = False) -> Dict[str, int]:
    """Delete all user-uploaded art from TV (not pre-loaded Samsung art).

    Args:
        client: Connected SamsungFrameClient
        force: Skip confirmation if True

    Returns:
        {'total': int, 'deleted': int, 'failed': int}
    """
    if not client.tv:
        raise RuntimeError("Not connected to TV")

    art_list = client.get_available_art()

    # Filter for user-uploaded photos only (content_id starts with MY_F)
    user_art = [art for art in art_list if art.get("content_id", "").startswith("MY_F")]
    total = len(user_art)

    if total == 0:
        logger.info("No user-uploaded art found on TV")
        return {"total": 0, "deleted": 0, "failed": 0}

    # Confirmation prompt
    if not force:
        response = input(f"Delete {total} user-uploaded art items from TV? [y/N]: ").strip().lower()
        if response != "y":
            logger.info("Deletion cancelled by user")
            return {"total": total, "deleted": 0, "failed": 0}

    logger.info(f"Deleting {total} user-uploaded art items from TV...")

    content_ids = [art.get("content_id") for art in user_art if art.get("content_id")]

    # Try batch delete first
    try:
        client.tv.art().delete_list(content_ids)
        logger.info(f"Successfully deleted {len(content_ids)} items")
        return {"total": total, "deleted": len(content_ids), "failed": 0}
    except Exception as e:
        logger.warning(f"Batch delete failed: {e}. Falling back to individual deletes...")

    # Fallback to individual deletes
    deleted = 0
    failed = 0

    for content_id in content_ids:
        try:
            client.tv.art().delete(content_id)
            deleted += 1
            logger.info(f"Deleted {content_id} ({deleted}/{len(content_ids)})")
        except Exception as e:
            logger.error(f"Failed to delete {content_id}: {e}")
            failed += 1

    logger.info(f"Deletion complete: {deleted} deleted, {failed} failed")
    return {"total": total, "deleted": deleted, "failed": failed}


def delete_art_by_ids(client: SamsungFrameClient, content_ids: List[str]) -> Dict[str, int]:
    """Delete specific art items by content ID.

    Args:
        client: Connected SamsungFrameClient
        content_ids: List of content IDs to delete

    Returns:
        {'total': int, 'deleted': int, 'failed': int}
    """
    if not client.tv:
        raise RuntimeError("Not connected to TV")

    total = len(content_ids)
    if total == 0:
        return {"total": 0, "deleted": 0, "failed": 0}

    logger.info(f"Deleting {total} art items...")

    # Try batch delete first with retry
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )
    def batch_delete() -> None:
        assert client.tv is not None
        client.tv.art().delete_list(content_ids)

    try:
        batch_delete()
        logger.info(f"Successfully deleted {total} items via batch delete")
        return {"total": total, "deleted": total, "failed": 0}
    except Exception as e:
        logger.warning(f"Batch delete failed after retries: {e}. Falling back to individual...")

    # Fallback to individual deletes with retry
    deleted = 0
    failed = 0

    for content_id in content_ids:

        @retry(
            stop=stop_after_attempt(2),
            wait=wait_exponential(multiplier=1, min=1, max=5),
            reraise=True,
        )
        def delete_single(cid: str) -> None:
            assert client.tv is not None
            client.tv.art().delete(cid)

        try:
            delete_single(content_id)
            deleted += 1
            logger.debug(f"Deleted {content_id} ({deleted}/{total})")
        except Exception as e:
            logger.error(f"Failed to delete {content_id} after retries: {e}")
            failed += 1

    logger.info(f"Individual deletion complete: {deleted} deleted, {failed} failed")
    return {"total": total, "deleted": deleted, "failed": failed}


def calculate_images_to_delete(
    existing_ids: List[str], successful_uploads: int, min_images: int
) -> List[str]:
    """Return IDs to delete, keeping enough to maintain min_images total.

    Args:
        existing_ids: List of existing content IDs before upload
        successful_uploads: Number of successfully uploaded images
        min_images: Minimum number of images to maintain on TV

    Returns:
        List of content IDs to delete (randomly selected if not deleting all)
    """
    total_after_upload = len(existing_ids) + successful_uploads
    if total_after_upload <= min_images:
        return []  # Keep all old images

    # Delete enough to leave min_images total
    delete_count = total_after_upload - min_images
    # Cap at existing count (can't delete more than we have)
    delete_count = min(delete_count, len(existing_ids))

    if delete_count >= len(existing_ids):
        return existing_ids  # Delete all old images

    # Randomly select which old images to delete
    return random.sample(existing_ids, delete_count)


def get_stale_art_ids(art_list: List[Dict[str, Any]], max_age_hours: int = 24) -> List[str]:
    """Return content IDs of user art older than max_age_hours using TV's image_date.

    Args:
        art_list: Full art list from art().available()
        max_age_hours: Max age in hours before art is considered stale

    Returns:
        List of stale content IDs
    """
    now = datetime.now(timezone.utc)
    stale: List[str] = []

    for art in art_list:
        content_id = art.get("content_id", "")
        if not content_id.startswith("MY_F"):
            continue

        image_date = art.get("image_date", "")
        if not image_date:
            stale.append(content_id)
            continue

        try:
            ts = datetime.strptime(image_date, "%Y:%m:%d %H:%M:%S").replace(tzinfo=timezone.utc)
            age_hours = (now - ts).total_seconds() / 3600
            if age_hours > max_age_hours:
                stale.append(content_id)
        except ValueError:
            stale.append(content_id)

    return stale


def prepare_images_to_temp_dir(
    images: List[Path], temp_dir: str
) -> tuple[List[ConversionResult], int]:
    """Convert HEIC and copy JPG/PNG into temp_dir with trimmed filenames.

    Returns:
        (conversion_results, processed_count)
    """
    converter = ImageConverter(temp_dir)
    results: List[ConversionResult] = []
    processed = 0
    seen: set[str] = set()

    for image_path in tqdm(images, desc="Preparing images", unit="img"):
        result = converter.convert_if_needed(image_path)
        results.append(result)

        if not result.success:
            continue

        processed += 1

        if result.converted_path:
            # HEIC was converted — rename to trimmed name
            converted = Path(result.converted_path)
            trimmed = trim_filename(converted.name, seen=seen)
            final_path = Path(temp_dir) / trimmed
            if converted != final_path:
                converted.rename(final_path)
            result.converted_path = str(final_path)
        else:
            # JPG/PNG — copy with trimmed name
            trimmed = trim_filename(image_path.name, seen=seen)
            final_path = Path(temp_dir) / trimmed
            shutil.copy2(image_path, final_path)
            result.converted_path = str(final_path)

    return results, processed


def run_batch_upload(args: argparse.Namespace) -> int:
    """Main workflow orchestration."""
    global _current_summary, _notification_sent
    _notification_sent = False

    # Register signal handlers for interrupt notification
    signal.signal(signal.SIGINT, _send_interrupt_notification)
    signal.signal(signal.SIGTERM, _send_interrupt_notification)

    cfg = get_config()
    logger.info("=" * 50)
    logger.info("Samsung Frame TV Batch Upload")
    logger.info("=" * 50)

    # Validate source directory
    if not os.path.isdir(args.source_dir):
        logger.error(f"Source directory not found: {args.source_dir}")
        return 1

    # Connect to TV and ensure art mode
    client = SamsungFrameClient(timeout=args.timeout)
    logger.info(f"Connecting to TV at {client.host}:{client.port} (timeout={args.timeout}s)...")
    if not client.connect():
        logger.error("Failed to connect to TV")
        return 1

    if not client.ensure_art_mode():
        logger.error("TV connected but art mode not available — check TV status")
        return 1

    # Discover images
    try:
        images = discover_images(args.source_dir, min_size_mb=cfg.samsung_frame.min_size_mb)
    except ValueError as e:
        logger.error(str(e))
        return 1

    if not images:
        logger.error("No images found matching criteria")
        return 1

    # Apply start-index then max-files
    if args.start_index > 0:
        logger.info(f"Skipping first {args.start_index} of {len(images)} discovered images")
        images = images[args.start_index :]

    if args.max_files > 0 and len(images) > args.max_files:
        logger.info(f"Limiting to first {args.max_files} of {len(images)} images")
        images = images[: args.max_files]

    if not images:
        logger.error("No images remaining after start-index/max-files filtering")
        return 1

    # --- Phase 1: Prepare files in temp dir (convert + trim filenames) ---
    art_deleted = 0
    art_delete_failures = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        logger.info(f"Using temp directory: {temp_dir}")
        conversion_results, processed_count = prepare_images_to_temp_dir(images, temp_dir)

        heic_converted = sum(
            1
            for r in conversion_results
            if r.success and Path(r.source_path).suffix.lower() == ".heic"
        )
        conversion_errors = [
            {"file": Path(r.source_path).name, "error": r.error_message or "Unknown error"}
            for r in conversion_results
            if not r.success
        ]

        if processed_count == 0:
            logger.error("All conversions failed")
            return 1

        # Update signal handler with conversion progress
        _current_summary = BatchUploadSummary(
            total_discovered=len(images),
            total_filtered=len(images),
            heic_converted=heic_converted,
            conversion_failures=len(conversion_errors),
            art_deleted=0,
            art_delete_failures=0,
            upload_summary=ImageUploadSummary(
                total_images=processed_count,
                successful_uploads=0,
                failed_uploads=0,
                uploaded_image_ids=[],
                errors=[],
            ),
            conversion_errors=conversion_errors,
        )

        # --- Phase 2: Upload from temp dir ---
        # Re-verify connection (may have gone stale during preparation)
        try:
            client.ping()
            logger.info("TV connection still active")
        except Exception:
            logger.warning("TV connection stale after preparation, reconnecting...")
            client.close()
            if not client.connect():
                logger.error("Failed to reconnect to TV")
                return 1

        matte = args.matte
        logger.info(f"Uploading {processed_count} images from temp dir...")
        upload_summary = client.upload_images_from_folder(temp_dir, matte=matte)

        # --- Purge: delete stale art using image_date from TV API ---
        # Purge runs even if uploads were partially aborted
        if not args.no_purge:
            purge_ready = True
            try:
                client.ping()
            except Exception:
                logger.warning("TV connection lost before purge, reconnecting...")
                client.close()
                if not client.connect():
                    logger.error("Cannot reconnect for purge — skipping purge")
                    purge_ready = False

            if purge_ready:
                art_list = client.get_available_art()
                user_art = [a for a in art_list if a.get("content_id", "").startswith("MY_F")]
                stale_ids = get_stale_art_ids(art_list)

                min_images = cfg.samsung_frame.min_images
                remaining = len(user_art) - len(stale_ids)
                if remaining < min_images:
                    keep_count = min_images - remaining
                    stale_ids = stale_ids[keep_count:]
                    logger.info(f"Keeping {keep_count} stale images to maintain min {min_images}")

                if stale_ids:
                    logger.info(f"Purging {len(stale_ids)} stale art items (>24h old)")
                    try:
                        result = delete_art_by_ids(client, stale_ids)
                        art_deleted = result["deleted"]
                        art_delete_failures = result["failed"]
                    except Exception as e:
                        logger.error(f"Error during purge: {e}")
                        art_delete_failures = len(stale_ids)
                else:
                    logger.info("No stale art to purge")

        # --- Summary ---
        summary = BatchUploadSummary(
            total_discovered=len(images),
            total_filtered=len(images),
            heic_converted=heic_converted,
            conversion_failures=len(conversion_errors),
            art_deleted=art_deleted,
            art_delete_failures=art_delete_failures,
            upload_summary=upload_summary,
            conversion_errors=conversion_errors,
        )
        _current_summary = summary

        send_batch_notification(summary)

        logger.info("=" * 50)
        logger.info("BATCH UPLOAD SUMMARY")
        logger.info(f"Discovered: {summary.total_discovered}")
        logger.info(f"Converted: {summary.heic_converted} HEIC files")
        logger.info(f"Deleted: {summary.art_deleted} existing art")
        logger.info(
            f"Uploaded: {summary.upload_summary.successful_uploads}/"
            f"{summary.upload_summary.total_images}"
        )
        logger.info(
            f"Failed: {summary.upload_summary.failed_uploads + summary.conversion_failures}"
        )
        logger.info("=" * 50)

        all_errors = conversion_errors + upload_summary.errors
        if all_errors:
            logger.error("Errors:")
            for err in all_errors[:5]:
                logger.error(f"  {err['file']}: {err['error']}")
            if len(all_errors) > 5:
                logger.error(f"  ... and {len(all_errors) - 5} more")

        # Enable art mode with exponential backoff retry
        if summary.upload_summary.successful_uploads > 0:
            delay = cfg.samsung_frame.slideshow_delay_seconds
            logger.info(f"Waiting {delay}s for TV to process uploads...")
            time.sleep(delay)
            logger.info("Starting slideshow...")

            @retry(
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                reraise=True,
            )
            def start_slideshow_with_retry() -> bool:
                return client.start_slideshow(duration=3, shuffle=True)

            if not start_slideshow_with_retry():
                logger.error("Slideshow start failed")
                return 1

        if client:
            client.close()

        return 0 if summary.upload_summary.successful_uploads > 0 else 1


def send_batch_notification(summary: BatchUploadSummary, interrupted: bool = False) -> None:
    """Send Pushover notification with batch upload results."""
    global _notification_sent
    _notification_sent = True

    total_failures = summary.upload_summary.failed_uploads + summary.conversion_failures

    if interrupted:
        priority = 1
        title = "Samsung Batch Upload - Interrupted"
    elif total_failures > 0:
        priority = 1  # High priority
        title = "Samsung Batch Upload - Partial Success"
    else:
        priority = 0
        title = "Samsung Batch Upload - Complete"

    message = (
        f"✓ Uploaded: {summary.upload_summary.successful_uploads}\n"
        f"✗ Failed: {total_failures}\n"
        f"🔄 Converted: {summary.heic_converted} HEIC\n"
        f"🗑 Deleted: {summary.art_deleted} existing"
    )

    try:
        pushover.send_message(message, title=title, priority=priority)
        logger.info("Notification sent")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def main() -> int:
    """Main entry point with command line interface."""
    cfg = get_config()
    parser = argparse.ArgumentParser(
        description="Batch upload images to Samsung Frame TV with HEIC conversion"
    )

    parser.add_argument("source_dir", help="Source directory (recursive search)")

    parser.add_argument(
        "--matte",
        default=cfg.samsung_frame.default_matte,
        help="Matte style (default: %(default)s)",
    )

    parser.add_argument(
        "--no-purge",
        action="store_true",
        help="Skip purging stale art (>24h old) after upload",
    )

    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Skip first N discovered files (applied before --max-files)",
    )

    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Maximum number of files to upload (0 = all)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="WebSocket timeout in seconds (default: 60)",
    )

    args = parser.parse_args()

    return run_batch_upload(args)


if __name__ == "__main__":
    sys.exit(main())
