"""Samsung Frame TV client for art mode management."""

import os
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, cast
from pydantic import BaseModel
from PIL import Image

from lib.logger import get_logger
from lib import Constants

from samsungtvws import SamsungTVWS


VALID_MATTE_COLORS = [
    "seafoam",
    "black",
    "neutral",
    "antique",
    "warm",
    "polar",
    "sand",
    "sage",
    "burgandy",
    "navy",
    "apricot",
    "byzantine",
    "lavender",
    "redorange",
    "skyblue",
    "turqoise",
]


class UploadResult(BaseModel):
    """Result of a single image upload."""

    image_path: str
    image_id: Optional[str]
    success: bool
    error_message: Optional[str] = None


class ImageUploadSummary(BaseModel):
    """Summary of batch image upload operation."""

    total_images: int
    successful_uploads: int
    failed_uploads: int
    uploaded_image_ids: List[str]
    errors: List[Dict[str, str]]


class SamsungFrameClient:
    """Client for Samsung Frame TV art mode management."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        token_file: Optional[str] = None,
    ):
        self.host = host or Constants.SAMSUNG_FRAME_IP
        self.port = port or Constants.SAMSUNG_FRAME_PORT
        self.token_file = token_file or Constants.SAMSUNG_FRAME_TOKEN_FILE

        if not self.host:
            raise ValueError("Samsung Frame TV IP address required")

        self.tv: Optional[SamsungTVWS] = None
        self.logger = get_logger(__name__)
        self.logger.info(f"Samsung Frame client initialized for {self.host}:{self.port}")

    def connect(self) -> bool:
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                if not os.path.exists(os.path.dirname(self.token_file)):
                    os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
                    self.logger.info(f"Created token directory: {os.path.dirname(self.token_file)}")

                if not os.path.exists(self.token_file):
                    self.logger.warning("No token file found - first-time authentication required")
                    self.logger.info("TV will display pairing prompt - accept on TV screen")
                    self.logger.info(f"Token will be saved to: {self.token_file}")

                self.tv = SamsungTVWS(
                    host=self.host, port=self.port, token_file=self.token_file, timeout=60
                )
                self.tv.open()
                self.tv.art().supported()
                self.logger.info(f"Connected to Samsung Frame TV at {self.host}")

                if os.path.exists(self.token_file):
                    os.chmod(self.token_file, 0o600)

                return True

            except ConnectionError as e:
                self.logger.error(f"Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    self.logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
            except Exception as e:
                self.logger.error(f"Unexpected error connecting to TV: {e}")
                return False

        self.logger.error(f"Failed to connect to TV at {self.host}:{self.port}")
        self.logger.error("Verify TV is powered on and on same network")
        return False

    def check_art_support(self) -> bool:
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return False

        try:
            support_info = self.tv.art().supported()
            self.logger.info(f"Art mode support: {support_info}")
            return bool(support_info)
        except Exception as e:
            self.logger.error(f"Error checking art mode support: {e}")
            return False

    def get_device_info(self) -> Optional[Dict[str, Any]]:
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return None

        try:
            device_info = self.tv.rest_device_info()
            return device_info
        except Exception as e:
            self.logger.error(f"Error getting device info: {e}")
            return None

    def validate_image_file(self, file_path: str) -> bool:
        try:
            if not os.path.exists(file_path):
                self.logger.error(f"File not found: {file_path}")
                return False

            ext = Path(file_path).suffix.lower().lstrip(".")
            if ext not in Constants.SAMSUNG_FRAME_SUPPORTED_FORMATS:
                self.logger.error(
                    f"Unsupported format: {ext}. "
                    f"Supported: {Constants.SAMSUNG_FRAME_SUPPORTED_FORMATS}"
                )
                return False

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > Constants.SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB:
                self.logger.error(
                    f"File too large: {file_size_mb:.2f}MB > "
                    f"{Constants.SAMSUNG_FRAME_MAX_IMAGE_SIZE_MB}MB"
                )
                return False

            with Image.open(file_path) as img:
                img.verify()

            return True

        except Exception as e:
            self.logger.error(f"Error validating image {file_path}: {e}")
            return False

    def upload_image(self, image_path: str, matte: Optional[str] = None) -> Optional[str]:
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return None

        matte = matte or Constants.SAMSUNG_FRAME_DEFAULT_MATTE

        try:
            if not self.validate_image_file(image_path):
                return None

            with open(image_path, "rb") as f:
                image_data = f.read()

            self.logger.info(f"Uploading {image_path} with matte '{matte}'...")
            image_id = self.tv.art().upload(image_data, matte=matte)
            self.logger.info(f"Successfully uploaded {image_path} -> ID: {image_id}")

            return str(image_id) if image_id else None

        except Exception as e:
            self.logger.error(f"Failed to upload {image_path}: {e}")
            return None

    def upload_images_from_folder(
        self, folder_path: str, matte: Optional[str] = None
    ) -> ImageUploadSummary:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        matte = matte or Constants.SAMSUNG_FRAME_DEFAULT_MATTE

        if not os.path.isdir(folder_path):
            raise ValueError(f"Folder not found: {folder_path}")

        image_files: List[str] = []
        for ext in Constants.SAMSUNG_FRAME_SUPPORTED_FORMATS:
            image_files.extend(str(f) for f in Path(folder_path).glob(f"*.{ext}"))
            image_files.extend(str(f) for f in Path(folder_path).glob(f"*.{ext.upper()}"))

        image_files = sorted(set(image_files))

        self.logger.info(f"Found {len(image_files)} images in {folder_path}")

        if not image_files:
            self.logger.warning(f"No images found in {folder_path}")
            return ImageUploadSummary(
                total_images=0,
                successful_uploads=0,
                failed_uploads=0,
                uploaded_image_ids=[],
                errors=[],
            )

        uploaded_ids: List[str] = []
        errors: List[Dict[str, str]] = []

        for image_path in image_files:
            try:
                image_id = self.upload_image(image_path, matte=matte)
                if image_id:
                    uploaded_ids.append(image_id)
                else:
                    errors.append(
                        {"file": os.path.basename(image_path), "error": "Upload returned None"}
                    )
            except Exception as e:
                self.logger.error(f"Error uploading {image_path}: {e}")
                errors.append({"file": os.path.basename(image_path), "error": str(e)})

        summary = ImageUploadSummary(
            total_images=len(image_files),
            successful_uploads=len(uploaded_ids),
            failed_uploads=len(errors),
            uploaded_image_ids=uploaded_ids,
            errors=errors,
        )

        self.logger.info(
            f"Upload complete: {summary.successful_uploads}/{summary.total_images} successful"
        )

        return summary

    def get_available_art(self) -> List[Dict[str, Any]]:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        try:
            art_list = self.tv.art().available()
            if isinstance(art_list, dict) and art_list.get("event") == "ms.channel.timeOut":
                self.logger.warning(
                    "TV art list request timed out - TV may be busy or slow to respond"
                )
                return []
            self.logger.info(f"Retrieved {len(art_list)} art items from TV")
            return cast(List[Dict[str, Any]], art_list)
        except Exception as e:
            self.logger.error(f"Error getting available art: {e}")
            return []

    def get_available_mattes(self) -> List[str]:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        try:
            matte_list = self.tv.art().get_matte_list()
            available_mattes = [matte_type for elem in matte_list for matte_type in elem.values()]
            self.logger.info(f"Retrieved {len(available_mattes)} available matte types")
            return available_mattes
        except Exception as e:
            self.logger.error(f"Error getting matte list: {e}")
            return []

    def update_all_mattes(self, matte: Optional[str] = None) -> Dict[str, int]:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        matte = matte or Constants.SAMSUNG_FRAME_DEFAULT_MATTE

        matte_list = self.tv.art().get_matte_list()
        available_mattes = [matte_type for elem in matte_list for matte_type in elem.values()]

        # Validate matte with optional color suffix
        if "_" in matte:
            base_matte, color = matte.rsplit("_", 1)
            if base_matte not in available_mattes:
                raise ValueError(
                    f"Invalid base matte type: {base_matte}. "
                    f"Supported: {', '.join(available_mattes)}"
                )
            if color not in VALID_MATTE_COLORS:
                raise ValueError(
                    f"Invalid color: {color}. Supported: {', '.join(VALID_MATTE_COLORS)}"
                )
        else:
            if matte not in available_mattes:
                raise ValueError(
                    f"Invalid matte type: {matte}. Supported: {', '.join(available_mattes)}"
                )

        art_list = self.get_available_art()
        if not art_list:
            self.logger.warning("No art found on TV to update")
            return {"total": 0, "updated": 0, "skipped": 0, "failed": 0}

        updated = 0
        skipped = 0
        failed = 0

        for art_item in art_list:
            content_id = art_item.get("content_id")
            current_matte = art_item.get("matte_id")

            if not content_id:
                self.logger.warning("Skipping art item without content_id")
                failed += 1
                continue

            if current_matte == matte:
                self.logger.info(f"Art {content_id} already has matte '{matte}', skipping")
                skipped += 1
                continue

            try:
                self.logger.info(
                    f"Changing matte for {content_id} from '{current_matte}' to '{matte}'"
                )
                self.tv.art().change_matte(content_id, matte)
                updated += 1
            except Exception as e:
                self.logger.error(f"Failed to update matte for art ID {content_id}: {e}")
                failed += 1

        self.logger.info(
            f"Matte update complete: {updated} updated, {skipped} skipped, {failed} failed"
        )
        return {"total": len(art_list), "updated": updated, "skipped": skipped, "failed": failed}

    def enable_art_mode(self) -> bool:
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return False

        try:
            self.tv.art().set_artmode(True)
            self.logger.info("Art mode enabled")
            return True
        except Exception as e:
            self.logger.error(f"Error enabling art mode: {e}")
            return False

    def start_slideshow(self) -> bool:
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return False

        try:
            if self.enable_art_mode():
                self.logger.info("Slideshow started with all uploaded images")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error starting slideshow: {e}")
            return False

    def download_thumbnails(self, output_dir: str, user_photos_only: bool = True) -> Dict[str, int]:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        if not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            self.logger.info(f"Created output directory: {output_dir}")

        art_list = self.get_available_art()
        if not art_list:
            self.logger.warning("No art found on TV")
            return {"total": 0, "downloaded": 0, "failed": 0}

        if user_photos_only:
            art_list = [art for art in art_list if art.get("content_id", "").startswith("MY_F")]
            self.logger.info(f"Filtering to {len(art_list)} user-uploaded photos")

        downloaded = 0
        failed = 0

        for art_item in art_list:
            content_id = art_item.get("content_id")
            if not content_id:
                self.logger.warning("Skipping art item without content_id")
                failed += 1
                continue

            try:
                self.logger.info(f"Downloading thumbnail for {content_id}...")
                thumbnail_data = self.tv.art().get_thumbnail(content_id)

                output_path = os.path.join(output_dir, f"{content_id}.jpg")
                with open(output_path, "wb") as f:
                    f.write(thumbnail_data)

                self.logger.info(f"Saved thumbnail to {output_path}")
                downloaded += 1
            except Exception as e:
                self.logger.error(f"Failed to download thumbnail for {content_id}: {e}")
                failed += 1

        self.logger.info(f"Thumbnail download complete: {downloaded} downloaded, {failed} failed")
        return {"total": len(art_list), "downloaded": downloaded, "failed": failed}

    def close(self) -> None:
        """Close connection to TV."""
        if self.tv:
            try:
                self.tv.close()
                self.logger.info("Closed connection to TV")
            except Exception as e:
                self.logger.warning(f"Error closing TV connection: {e}")
