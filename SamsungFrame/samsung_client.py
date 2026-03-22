"""Samsung Frame TV client for art mode management."""

import os
import signal
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from PIL import Image
from pydantic import BaseModel
from samsungtvws import SamsungTVWS
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

from lib.config import get_config
from lib.logger import get_logger

cfg = get_config()

ART_UPLOAD_TIMEOUT = 30

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
        timeout: int = 60,
    ):
        self.host = host or cfg.samsung_frame.ip
        self.port = port or cfg.samsung_frame.port
        self.token_file = token_file or cfg.samsung_frame.token_file
        self.timeout = timeout

        if not self.host:
            raise ValueError("Samsung Frame TV IP address required")

        self.tv: Optional[SamsungTVWS] = None
        self.logger = get_logger(__name__)
        self.logger.info(f"Samsung Frame client initialized for {self.host}:{self.port}")

    def __enter__(self) -> "SamsungFrameClient":
        """Context manager: connect_ready() and return client."""
        if not self.connect_ready():
            raise ConnectionError(f"Failed to get TV ready at {self.host}")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

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
                    host=self.host, port=self.port, token_file=self.token_file, timeout=self.timeout
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

    def _send_wol(self) -> bool:
        """Send Wake-on-LAN magic packets to TV.

        Hardened strategy: sends 3 rounds to both broadcast and directed IP,
        on ports 9 and 7, with optional SecureON password support.
        """
        mac = cfg.samsung_frame.mac
        if not mac:
            self.logger.warning("No MAC address configured — cannot send Wake-on-LAN")
            return False

        try:
            mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
            magic = b"\xff" * 6 + mac_bytes * 16

            wol_password = getattr(cfg.samsung_frame, "wol_password", None)
            if wol_password:
                pwd_bytes = bytes.fromhex(wol_password.replace(":", "").replace("-", ""))
                magic += pwd_bytes

            targets = [("<broadcast>", 9), ("<broadcast>", 7)]
            if self.host:
                targets.extend([(self.host, 9), (self.host, 7)])

            for attempt in range(3):
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    for addr, port in targets:
                        s.sendto(magic, (addr, port))
                if attempt < 2:
                    time.sleep(0.5)

            self.logger.info(
                f"Wake-on-LAN sent to {mac} (3 rounds, {len(targets)} targets"
                f"{', SecureON' if wol_password else ''})"
            )
            return True
        except Exception as e:
            self.logger.error(f"Wake-on-LAN failed: {e}")
            return False

    def _smartthings_power_on(self) -> bool:
        """Power on TV via SmartThings cloud API (fallback when WoL fails)."""
        token = getattr(cfg.samsung_frame, "smartthings_token", None)
        device_id = getattr(cfg.samsung_frame, "smartthings_device_id", None)
        if not token or not device_id:
            return False

        import requests

        try:
            resp = requests.post(
                f"https://api.smartthings.com/v1/devices/{device_id}/commands",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "commands": [
                        {
                            "component": "main",
                            "capability": "switch",
                            "command": "on",
                        }
                    ]
                },
                timeout=10,
            )
            if resp.ok:
                self.logger.info("SmartThings power-on command sent")
                return True
            self.logger.warning(f"SmartThings power-on failed: {resp.status_code} {resp.text}")
            return False
        except Exception as e:
            self.logger.error(f"SmartThings API error: {e}")
            return False

    def _is_tv_reachable(self) -> bool:
        """Check if TV REST API is reachable (works in standby)."""
        try:
            from samsungtvws.rest import SamsungTVRest

            rest = SamsungTVRest(self.host, port=8001, timeout=3)
            rest.rest_device_info()
            return True
        except Exception:
            return False

    def _wake_and_connect(self) -> bool:
        """Send WoL + SmartThings, then establish WebSocket connection.

        This is the ONLY method that should be used to (re)connect to the TV.
        Handles wake-from-off via WoL/SmartThings, standby via REST detection,
        and direct WebSocket connect when TV is already on.
        """
        self._send_wol()
        self._smartthings_power_on()

        if self.connect():
            return True

        # Connect failed — check if TV is reachable via REST (standby)
        if self._is_tv_reachable():
            self.logger.info("TV in standby, waiting for WebSocket...")
            time.sleep(5)
            if self.connect():
                return True

        # TV still unreachable — wait for WoL/SmartThings to take effect
        if self._wait_for_power(target_on=True, timeout=60, poll_interval=3):
            time.sleep(5)
            return self.connect()

        return False

    def connect_ready(self) -> bool:
        """Get TV to art-mode-ready state from any starting state.

        Handles: TV off → WoL → wait → connect → art mode
                 TV standby → connect → art mode
                 TV on (regular) → connect → toggle to art mode
                 TV in art mode → connect → verify
        """
        if self._wake_and_connect():
            if self.ensure_art_mode():
                return True
            self.logger.warning("Connected but art mode failed — rebooting...")
            return self._reboot_and_reconnect()

        self.logger.error("Cannot reach TV — verify power and network")
        return False

    def ping(self) -> bool:
        """Lightweight health check via art().supported(). Raises on failure."""
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        self.tv.art().supported()
        return True

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
            cfg = get_config()
            if not os.path.exists(file_path):
                self.logger.error(f"File not found: {file_path}")
                return False

            ext = Path(file_path).suffix.lower().lstrip(".")
            if ext not in cfg.samsung_frame.supported_formats:
                self.logger.error(
                    f"Unsupported format: {ext}. Supported: {cfg.samsung_frame.supported_formats}"
                )
                return False

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > cfg.samsung_frame.max_image_size_mb:
                self.logger.error(
                    f"File too large: {file_size_mb:.2f}MB > "
                    f"{cfg.samsung_frame.max_image_size_mb}MB"
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

        cfg = get_config()

        matte = matte or cfg.samsung_frame.default_matte

        if not self.validate_image_file(image_path):
            return None

        try:
            with open(image_path, "rb") as f:
                image_data = f.read()

            file_ext = Path(image_path).suffix.lower().lstrip(".")
            if file_ext == "jpeg":
                file_ext = "jpg"

            assert self.tv is not None
            self.logger.debug(f"Uploading {image_path} ({file_ext}) with matte '{matte}'...")

            def _timeout_handler(_signum: int, _frame: Any) -> None:
                raise TimeoutError(f"Upload exceeded {ART_UPLOAD_TIMEOUT}s")

            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(ART_UPLOAD_TIMEOUT)
            try:
                image_id = self.tv.art(timeout=10).upload(
                    image_data, matte=matte, file_type=file_ext
                )
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            self.logger.debug(f"Successfully uploaded {image_path} -> ID: {image_id}")
            return str(image_id) if image_id else None

        except TimeoutError:
            self.logger.error(f"Upload timed out after {ART_UPLOAD_TIMEOUT}s: {image_path}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to upload {image_path}: {e}")
            return None

    def upload_images_from_folder(
        self, folder_path: str, matte: Optional[str] = None, max_consecutive_failures: int = 3
    ) -> ImageUploadSummary:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        cfg = get_config()
        matte = matte or cfg.samsung_frame.default_matte

        if not os.path.isdir(folder_path):
            raise ValueError(f"Folder not found: {folder_path}")

        image_files: List[str] = []
        for ext in cfg.samsung_frame.supported_formats:
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
        consecutive_failures = 0
        rebooted = False
        known_ids = self._get_art_ids_on_tv()
        pause = 5
        min_pause = 5
        max_pause = 30

        pbar = tqdm(image_files, desc="Uploading images", unit="img")
        for image_path in pbar:
            pbar.set_postfix_str(os.path.basename(image_path))
            recovered = False
            try:
                image_id = self.upload_image(image_path, matte=matte)
                if image_id:
                    uploaded_ids.append(image_id)
                    known_ids.add(image_id)
                    consecutive_failures = 0
                    self.logger.debug(f"Uploaded {os.path.basename(image_path)} -> {image_id}")
                else:
                    new_id = self._check_for_new_upload(known_ids)
                    if new_id:
                        uploaded_ids.append(new_id)
                        known_ids.add(new_id)
                        consecutive_failures = 0
                        self.logger.debug(
                            f"Uploaded {os.path.basename(image_path)} (recovered from timeout)"
                        )
                    else:
                        recovered = True
                        errors.append(
                            {"file": os.path.basename(image_path), "error": "Upload returned None"}
                        )
                        consecutive_failures += 1
            except Exception as e:
                self.logger.error(f"Error uploading {image_path}: {e}")
                new_id = self._check_for_new_upload(known_ids)
                if new_id:
                    uploaded_ids.append(new_id)
                    known_ids.add(new_id)
                    consecutive_failures = 0
                    self.logger.debug(
                        f"Uploaded {os.path.basename(image_path)} (recovered from error)"
                    )
                else:
                    recovered = True
                    errors.append({"file": os.path.basename(image_path), "error": str(e)})
                    consecutive_failures += 1
            finally:
                if recovered:
                    pause = min(pause + 5, max_pause)
                    self.logger.info(f"TV needs cooldown, pausing {pause}s")
                else:
                    pause = max(pause - 1, min_pause)
                time.sleep(pause)
                if not self.ensure_art_mode():
                    self.logger.warning("Lost art mode, attempting reboot recovery...")
                    if not self._reboot_and_reconnect():
                        self.logger.error("Cannot recover art mode — stopping uploads")
                        break

            if consecutive_failures >= max_consecutive_failures:
                self.logger.warning(f"{consecutive_failures} consecutive failures — recovering...")
                if self.ensure_art_mode():
                    consecutive_failures = 0
                    continue
                if not rebooted:
                    self.logger.warning("Art mode recovery failed — rebooting TV...")
                    if self._reboot_and_reconnect():
                        rebooted = True
                        consecutive_failures = 0
                        continue
                self.logger.error(
                    f"{consecutive_failures} consecutive failures — "
                    f"recovery failed, stopping uploads"
                )
                break

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

    def _get_art_ids_on_tv(self) -> set[str]:
        """Get current set of user-uploaded art IDs on TV."""
        try:
            art_list = self.get_available_art()
            return {
                a.get("content_id", "")
                for a in art_list
                if a.get("content_id", "").startswith("MY_F")
            }
        except Exception:
            return set()

    def _check_for_new_upload(self, known_ids: set[str]) -> Optional[str]:
        """Check if a new art ID appeared on TV (upload succeeded despite timeout)."""
        try:
            current_ids = self._get_art_ids_on_tv()
            new_ids = current_ids - known_ids
            if new_ids:
                return new_ids.pop()
        except Exception:
            pass
        return None

    def ensure_art_mode(self) -> bool:
        """Ensure TV is in art mode. Try art API first, power-cycle if needed.

        Frame TVs boot into art mode from standby, so: KEY_POWER (off) → wait →
        reconnect (wakes into art mode).

        Returns:
            True if TV is confirmed in art mode with art API responding
        """
        if not self.tv:
            if not self._wake_and_connect():
                return False

        # Already in art mode?
        try:
            self.get_available_art_strict()
            self.logger.debug("Art mode confirmed, API responding")
            return True
        except Exception:
            pass

        # KEY_POWER toggles: TV mode → off, off → art mode
        # May need two toggles if TV is in regular mode
        self.logger.info("Art API not responding, toggling KEY_POWER into art mode...")
        try:
            if self.tv:
                self.tv.send_key("KEY_POWER")
        except Exception:
            pass
        self.close()

        for attempt in range(1, 4):
            wait = 10 * attempt
            self.logger.info(f"Waiting {wait}s for art mode (attempt {attempt}/3)...")
            time.sleep(wait)
            try:
                if self._wake_and_connect():
                    self.get_available_art_strict()
                    self.logger.info("Art mode activated via KEY_POWER toggle")
                    return True
            except Exception:
                self.close()

        self.logger.error("Failed to activate art mode after retries")
        return False

    def _reconnect(self) -> bool:
        """Close and re-establish TV connection."""
        self.logger.info("Closing stale connection...")
        self.close()
        time.sleep(2)
        return self._wake_and_connect()

    def _wait_for_power(self, target_on: bool, timeout: int = 120, poll_interval: int = 3) -> bool:
        """Poll REST API until TV power state matches target or timeout.

        REST API (HTTP GET on port 8001) works without WebSocket — lightweight check.
        """
        from samsungtvws.rest import SamsungTVRest

        rest = SamsungTVRest(self.host, port=8001, timeout=5)
        state_name = "on" if target_on else "off"
        elapsed = 0

        while elapsed < timeout:
            try:
                is_on = rest.rest_power_state()
                if is_on == target_on:
                    self.logger.info(f"TV power state is {state_name}")
                    return True
            except Exception:
                if not target_on:
                    # Connection refused = TV is off
                    self.logger.info("TV is off (REST unreachable)")
                    return True
            time.sleep(poll_interval)
            elapsed += poll_interval

        self.logger.warning(f"Timed out waiting for TV to be {state_name}")
        return False

    def _reboot_and_reconnect(self, max_attempts: int = 3) -> bool:
        """Reboot TV, poll for power cycle, reconnect into art mode."""
        if not self.reboot():
            # No WebSocket connection — try WoL to wake TV instead
            self.logger.info("Cannot reboot (not connected) — trying WoL wake...")
            if not self._send_wol():
                self.logger.error("No connection and WoL failed — cannot proceed")
                return False

        # Wait for TV to go down (or timeout — it may already be restarting)
        self._wait_for_power(target_on=False, timeout=15, poll_interval=2)

        # Wait for TV to come back up
        if not self._wait_for_power(target_on=True, timeout=120, poll_interval=5):
            self.logger.error("TV did not come back after reboot")
            return False

        # TV is up — connect and get into art mode
        for attempt in range(1, max_attempts + 1):
            self.logger.info(f"Connecting to art mode (attempt {attempt}/{max_attempts})...")
            try:
                if self._wake_and_connect() and self.ensure_art_mode():
                    self.logger.info("Reconnected after reboot, art mode verified")
                    return True
            except Exception:
                self.close()
            time.sleep(5)

        self.logger.error("TV is up but art mode failed")
        return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _fetch_art_list(self) -> List[Dict[str, Any]]:
        """Fetch art list with retry. Raises on error."""
        assert self.tv is not None
        art_list = self.tv.art().available()
        if isinstance(art_list, dict) and art_list.get("event") == "ms.channel.timeOut":
            raise TimeoutError("TV art list request timed out")
        return cast(List[Dict[str, Any]], art_list)

    def get_available_art_strict(self) -> List[Dict[str, Any]]:
        """Get available art, raising on error instead of returning []."""
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        art_list = self._fetch_art_list()
        user_count = sum(1 for a in art_list if a.get("content_id", "").startswith("MY_F"))
        self.logger.debug(f"Retrieved {user_count} user uploaded images from TV")
        return art_list

    def get_available_art(self) -> List[Dict[str, Any]]:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        try:
            art_list = self._fetch_art_list()
            user_count = sum(1 for a in art_list if a.get("content_id", "").startswith("MY_F"))
            self.logger.debug(f"Retrieved {user_count} user uploaded images from TV")
            return art_list
        except Exception as e:
            self.logger.error(f"Error getting available art after retries: {e}")
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

    def update_all_mattes(
        self, matte: Optional[str] = None, user_photos_only: bool = True
    ) -> Dict[str, int]:
        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        cfg = get_config()
        matte = matte or cfg.samsung_frame.default_matte

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

        # Filter for user-uploaded art only if requested
        if user_photos_only:
            art_list = [art for art in art_list if art.get("content_id", "").startswith("MY_F")]

        if not art_list:
            self.logger.warning("No art found on TV to update")
            return {"total": 0, "updated": 0, "skipped": 0, "failed": 0}

        updated = 0
        skipped = 0
        failed = 0

        for art_item in tqdm(art_list, desc="Updating mattes", unit="art"):
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

            time.sleep(1)
            try:
                self.ping()
            except Exception:
                self.logger.warning("Connection lost, reconnecting...")
                if not self._reconnect():
                    self.logger.error("Reconnect failed — stopping matte updates")
                    break

        self.logger.info(
            f"Matte update complete: {updated} updated, {skipped} skipped, {failed} failed"
        )
        return {"total": len(art_list), "updated": updated, "skipped": skipped, "failed": failed}

    def enable_art_mode(self) -> bool:
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return False

        try:
            status = self.tv.art().get_artmode()
            if status == "on":
                self.logger.info("Already in art mode")
                return True
        except Exception:
            pass

        try:
            self.tv.art().set_artmode(True)
            self.logger.info("Art mode enabled")
            return True
        except Exception as e:
            if "timed out" in str(e).lower():
                self.logger.debug("Art mode set timed out (likely already in art mode)")
                return True
            self.logger.error(f"Error enabling art mode: {e}")
            return False

    def start_slideshow(self, duration: int = 15, shuffle: bool = True) -> bool:
        """Start slideshow with automatic image cycling. Retries up to 3 times.

        Args:
            duration: Time in minutes between image changes (default: 15)
            shuffle: Enable shuffle mode (default: True)

        Returns:
            True if slideshow started successfully
        """
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return False

        self.enable_art_mode()

        for attempt in range(1, 4):
            try:
                self.tv.art().set_slideshow_status(duration=duration, type=shuffle, category=2)
                self.logger.info(
                    f"Slideshow started: {duration}min interval, "
                    f"{'shuffle' if shuffle else 'sequential'} mode"
                )
                return True
            except Exception as e:
                # slideshow_image_changed response means it's actually working
                err_str = str(e)
                if "slideshow_image_changed" in err_str:
                    self.logger.info("Slideshow confirmed running (image changed event)")
                    return True
                self.logger.warning(f"Slideshow attempt {attempt}/3 failed: {e}")
                time.sleep(2)

        self.logger.error("Failed to start slideshow after 3 attempts")
        return False

    def cycle_images(
        self, period: int = 15, user_photos_only: bool = True, shuffle: bool = True
    ) -> None:
        """Cycle through images on TV with specified period.

        Args:
            period: Time in seconds between image changes (default: 15)
            user_photos_only: Only cycle through user-uploaded photos (default: True)
            shuffle: Randomize image order each cycle (default: True)

        Raises:
            RuntimeError: If not connected to TV
            KeyboardInterrupt: When user stops the cycle
        """
        import random

        if not self.tv:
            raise RuntimeError("Not connected to TV - call connect() first")

        art_list = self.get_available_art()
        if not art_list:
            self.logger.warning("No art found on TV")
            return

        if user_photos_only:
            art_list = [art for art in art_list if art.get("content_id", "").startswith("MY_F")]
            self.logger.info(f"Cycling through {len(art_list)} user-uploaded photos")
        else:
            self.logger.info(f"Cycling through {len(art_list)} art items")

        if not art_list:
            self.logger.warning("No art items to cycle through")
            return

        self.enable_art_mode()
        self.logger.info(
            f"Starting image cycle with {period} second period "
            f"({'shuffle' if shuffle else 'sequential'} mode)"
        )
        self.logger.info("Press Ctrl+C to stop")

        try:
            cycle_count = 0
            while True:
                # Shuffle list at start of each cycle if enabled
                if shuffle:
                    random.shuffle(art_list)

                for art_item in art_list:
                    content_id = art_item.get("content_id")
                    if not content_id:
                        continue

                    try:
                        self.tv.art().select_image(content_id)
                        self.logger.info(f"Displaying: {content_id}")
                        time.sleep(period)
                    except Exception as e:
                        self.logger.error(f"Failed to display {content_id}: {e}")
                        continue

                cycle_count += 1
                self.logger.info(f"Completed cycle {cycle_count}")

        except KeyboardInterrupt:
            self.logger.info(f"Image cycling stopped after {cycle_count} complete cycles")

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

    def reboot(self) -> bool:
        """Hard reboot TV via 5s power hold. Does not wait for TV to come back.

        hold_key sends Press, sleeps 5s, sends Release. The TV reboots mid-hold,
        dropping the WebSocket — the resulting exception is the expected success path.
        Always returns True once hold_key is called.
        """
        if not self.tv:
            self.logger.error("Not connected to TV - call connect() first")
            return False

        try:
            self.logger.info("Sending hold_key(KEY_POWER, 5) for hard reboot...")
            self.tv.hold_key("KEY_POWER", 5)
        except Exception as e:
            self.logger.info(f"hold_key interrupted (expected during reboot): {e}")
        finally:
            self.close()
        return True

    def close(self) -> None:
        """Close connection to TV."""
        if self.tv:
            try:
                self.tv.close()
                self.logger.info("Closed connection to TV")
            except Exception as e:
                self.logger.warning(f"Error closing TV connection: {e}")
