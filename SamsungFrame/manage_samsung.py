#!/usr/bin/env python3
"""Main entry point for Samsung Frame TV art mode management."""

import argparse
import sys

from SamsungFrame.samsung_client import SamsungFrameClient, ImageUploadSummary
from lib.MyPushover import Pushover
from lib.logger import get_logger
from lib import Constants

pushover = Pushover(
    Constants.PUSHOVER_USER,
    Constants.PUSHOVER_TOKENS.get("SamsungFrame", Constants.PUSHOVER_DEFAULT_TOKEN),
)


def main() -> int:
    """Main entry point with command line interface."""
    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info("Starting Samsung Frame TV Art Manager")

    parser = argparse.ArgumentParser(description="Samsung Frame TV Art Mode Manager")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    upload_parser = subparsers.add_parser("upload", help="Upload images from folder to TV")
    upload_parser.add_argument("folder", type=str, help="Path to folder containing images")
    upload_parser.add_argument(
        "--matte",
        type=str,
        default=None,
        help=f"Matte style (default: {Constants.SAMSUNG_FRAME_DEFAULT_MATTE})",
    )
    upload_parser.add_argument(
        "--notify", action="store_true", help="Send notification when complete"
    )

    subparsers.add_parser("status", help="Check TV connection and art mode support")
    subparsers.add_parser("list-art", help="List available art on TV")
    subparsers.add_parser("list-mattes", help="List available matte styles")

    download_parser = subparsers.add_parser(
        "download-thumbnails", help="Download thumbnails for art on TV"
    )
    download_parser.add_argument("output_dir", type=str, help="Directory to save thumbnails")
    download_parser.add_argument(
        "--all", action="store_true", help="Download all art (not just user photos)"
    )

    matte_parser = subparsers.add_parser(
        "update-mattes", help="Update matte style for all art on TV"
    )
    matte_parser.add_argument(
        "--matte",
        type=str,
        default=None,
        help=f"Matte style (default: {Constants.SAMSUNG_FRAME_DEFAULT_MATTE})",
    )

    cycle_parser = subparsers.add_parser(
        "cycle-images", help="Cycle through images with specified period"
    )
    cycle_parser.add_argument(
        "--period",
        type=int,
        default=15,
        help="Time in seconds between image changes (default: 15)",
    )
    cycle_parser.add_argument(
        "--all", action="store_true", help="Cycle through all art (not just user photos)"
    )

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Route to appropriate handler
    if args.command == "upload":
        return run_upload(args)
    elif args.command == "status":
        return show_status(args)
    elif args.command == "list-art":
        return list_art(args)
    elif args.command == "list-mattes":
        return list_mattes(args)
    elif args.command == "download-thumbnails":
        return download_thumbnails(args)
    elif args.command == "update-mattes":
        return update_mattes(args)
    elif args.command == "cycle-images":
        return cycle_images(args)

    return 0


def run_upload(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)

    try:
        client = SamsungFrameClient()
        logger.info(f"Connecting to Samsung Frame TV at {client.host}...")

        if not client.connect():
            error_msg = f"Failed to connect to TV at {client.host}"
            logger.error(error_msg)
            pushover.send_message(
                f"{error_msg}\nCheck TV is powered on and on network",
                title="SamsungFrame Error",
                priority=1,
            )
            return 1

        if not client.check_art_support():
            error_msg = "TV does not support art mode"
            logger.error(error_msg)
            pushover.send_message(
                error_msg,
                title="SamsungFrame Error",
                priority=1,
            )
            return 1

        logger.info(f"Uploading images from {args.folder}...")
        matte = args.matte or Constants.SAMSUNG_FRAME_DEFAULT_MATTE
        summary: ImageUploadSummary = client.upload_images_from_folder(args.folder, matte=matte)

        logger.info(
            f"Upload complete: {summary.successful_uploads}/{summary.total_images} successful"
        )

        if summary.failed_uploads > 0:
            logger.warning(f"Failed uploads: {summary.failed_uploads}")
            for error in summary.errors:
                logger.warning(f"  - {error['file']}: {error['error']}")

        if summary.successful_uploads > 0:
            logger.info("Enabling art mode and starting slideshow...")
            if client.start_slideshow():
                logger.info("Art mode enabled with slideshow")

                if args.notify or summary.failed_uploads > 0:
                    send_upload_notification(summary, matte)
            else:
                error_msg = "Failed to enable art mode"
                logger.error(error_msg)
                pushover.send_message(
                    error_msg,
                    title="SamsungFrame Error",
                    priority=1,
                )
                return 1
        else:
            error_msg = "No images uploaded successfully"
            logger.error(error_msg)
            send_upload_notification(summary, matte)
            return 1

        logger.info("Upload workflow complete!")
        client.close()
        return 0

    except KeyboardInterrupt:
        logger.info("Upload cancelled by user")
        return 0
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        pushover.send_message(
            f"Configuration error: {e}",
            title="SamsungFrame Error",
            priority=1,
        )
        return 1
    except Exception as e:
        logger.error(f"Unexpected error during upload: {e}")
        pushover.send_message(
            f"Unexpected error: {e}",
            title="SamsungFrame Error",
            priority=1,
        )
        return 1
    finally:
        if "client" in locals():
            client.close()


def show_status(_args: argparse.Namespace) -> int:
    logger = get_logger(__name__)

    try:
        client = SamsungFrameClient()
        logger.info(f"Connecting to Samsung Frame TV at {client.host}...")

        if not client.connect():
            logger.error(f"Failed to connect to TV at {client.host}")
            logger.error("Verify TV is powered on and on same network")
            return 1

        logger.info("=" * 50)
        logger.info("TV STATUS")
        logger.info("=" * 50)

        device_info = client.get_device_info()
        if device_info:
            device = device_info.get("device", {})
            logger.info(f"Model: {device.get('modelName', 'Unknown')}")
            logger.info(f"Name: {device.get('name', 'Unknown')}")
            logger.info(f"Firmware: {device.get('firmwareVersion', 'Unknown')}")
            logger.info(f"Resolution: {device.get('resolution', 'Unknown')}")
            logger.info(f"Power State: {device.get('PowerState', 'Unknown')}")
            logger.info(f"OS: {device.get('OS', 'Unknown')}")
            logger.info(f"Network Type: {device.get('networkType', 'Unknown')}")

            frame_tv = device.get("FrameTVSupport", "false")
            logger.info(f"Frame TV Support: {frame_tv}")

            if frame_tv == "true":
                art_list = client.get_available_art()
                logger.info(f"Available Art: {len(art_list)} items")
        else:
            logger.warning("Could not retrieve device info")

        if client.check_art_support():
            logger.info("Art Mode: Supported and working")
        else:
            logger.warning("Art Mode: Not supported or unavailable")

        client.close()
        return 0

    except Exception as e:
        logger.error(f"Error checking status: {e}")
        return 1
    finally:
        if "client" in locals():
            client.close()


def list_art(_args: argparse.Namespace) -> int:
    logger = get_logger(__name__)

    try:
        client = SamsungFrameClient()
        logger.info(f"Connecting to Samsung Frame TV at {client.host}...")

        if not client.connect():
            logger.error(f"Failed to connect to TV at {client.host}")
            return 1

        logger.info("Retrieving available art...")
        art_list = client.get_available_art()

        if not art_list:
            logger.info("No art available on TV")
            return 0

        logger.info(f"Available art ({len(art_list)} items):")
        for i, art in enumerate(art_list, 1):
            art_id = art.get("content_id", "Unknown ID")
            logger.info(f"  {i}. ID: {art_id}")

        client.close()
        return 0

    except Exception as e:
        logger.error(f"Error listing art: {e}")
        return 1
    finally:
        if "client" in locals():
            client.close()


def list_mattes(_args: argparse.Namespace) -> int:
    logger = get_logger(__name__)

    try:
        client = SamsungFrameClient()
        logger.info(f"Connecting to Samsung Frame TV at {client.host}...")

        if not client.connect():
            logger.error(f"Failed to connect to TV at {client.host}")
            return 1

        logger.info("Retrieving available matte styles...")
        mattes = client.get_available_mattes()

        if not mattes:
            logger.warning("No matte styles available")
            return 0

        logger.info(f"Available matte styles ({len(mattes)} options):")
        for i, matte in enumerate(mattes, 1):
            logger.info(f"  {i}. {matte}")

        client.close()
        return 0

    except Exception as e:
        logger.error(f"Error listing mattes: {e}")
        return 1
    finally:
        if "client" in locals():
            client.close()


def download_thumbnails(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)

    try:
        client = SamsungFrameClient()
        logger.info(f"Connecting to Samsung Frame TV at {client.host}...")

        if not client.connect():
            logger.error(f"Failed to connect to TV at {client.host}")
            return 1

        user_photos_only = not args.all
        if user_photos_only:
            logger.info("Downloading thumbnails for user-uploaded photos only...")
        else:
            logger.info("Downloading thumbnails for all art on TV...")

        result = client.download_thumbnails(args.output_dir, user_photos_only=user_photos_only)

        logger.info(
            f"Results: {result['downloaded']} downloaded, "
            f"{result['failed']} failed (Total: {result['total']})"
        )

        client.close()
        return 0 if result["failed"] == 0 else 1

    except Exception as e:
        logger.error(f"Error downloading thumbnails: {e}")
        return 1
    finally:
        if "client" in locals():
            client.close()


def update_mattes(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)

    try:
        client = SamsungFrameClient()
        logger.info(f"Connecting to Samsung Frame TV at {client.host}...")

        if not client.connect():
            logger.error(f"Failed to connect to TV at {client.host}")
            return 1

        matte = args.matte or Constants.SAMSUNG_FRAME_DEFAULT_MATTE
        logger.info(f"Updating all art mattes to '{matte}'...")

        result = client.update_all_mattes(matte)

        logger.info(
            f"Results: {result['updated']} updated, "
            f"{result['skipped']} skipped, "
            f"{result['failed']} failed (Total: {result['total']})"
        )

        client.close()
        return 0 if result["failed"] == 0 else 1

    except Exception as e:
        logger.error(f"Error updating mattes: {e}")
        return 1
    finally:
        if "client" in locals():
            client.close()


def cycle_images(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)

    try:
        client = SamsungFrameClient()
        logger.info(f"Connecting to Samsung Frame TV at {client.host}...")

        if not client.connect():
            logger.error(f"Failed to connect to TV at {client.host}")
            return 1

        user_photos_only = not args.all
        client.cycle_images(period=args.period, user_photos_only=user_photos_only)

        client.close()
        return 0

    except KeyboardInterrupt:
        logger.info("Image cycling stopped by user")
        return 0
    except Exception as e:
        logger.error(f"Error cycling images: {e}")
        return 1
    finally:
        if "client" in locals():
            client.close()


def send_upload_notification(summary: ImageUploadSummary, matte: str) -> None:
    if summary.successful_uploads == 0:
        error_details = "\n".join([f"- {e['file']}: {e['error']}" for e in summary.errors[:5]])
        pushover.send_message(
            f"Failed to upload all {summary.total_images} images\n\n{error_details}",
            title="SamsungFrame Upload Failed",
            priority=1,
        )
    elif summary.failed_uploads > 0:
        failed_files = [e["file"] for e in summary.errors[:5]]
        more_text = f" (+{len(summary.errors) - 5} more)" if len(summary.errors) > 5 else ""
        pushover.send_message(
            f"Uploaded {summary.successful_uploads}/{summary.total_images} images\n"
            f"Matte: {matte}\n"
            f"Art mode enabled with slideshow\n\n"
            f"Failed: {', '.join(failed_files)}{more_text}",
            title="SamsungFrame Upload Complete (with errors)",
        )
    else:
        pushover.send_message(
            f"Uploaded {summary.successful_uploads} images to Samsung Frame\n"
            f"Matte: {matte}\n"
            f"Art mode enabled with slideshow",
            title="SamsungFrame Upload Complete",
        )


if __name__ == "__main__":
    sys.exit(main())
