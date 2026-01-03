#!/usr/bin/env python3
"""Main entry point for Samsung Frame TV art mode management."""

import argparse
import sys


from SamsungFrame.samsung_client import SamsungFrameClient
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
        "update-mattes", help="Update matte style for user-uploaded art (use --all for all art)"
    )
    matte_parser.add_argument(
        "--matte",
        type=str,
        default=None,
        help=f"Matte style (default: {Constants.SAMSUNG_FRAME_DEFAULT_MATTE})",
    )
    matte_parser.add_argument(
        "--all",
        action="store_true",
        help="Update all art (including Samsung pre-installed art)",
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
    cycle_parser.add_argument(
        "--no-shuffle",
        action="store_true",
        help="Disable randomization (cycle in sequential order)",
    )

    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Route to appropriate handler
    if args.command == "status":
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
        user_photos_only = not args.all

        if user_photos_only:
            logger.info(f"Updating user-uploaded art mattes to '{matte}'...")
        else:
            logger.info(f"Updating all art mattes to '{matte}'...")

        result = client.update_all_mattes(matte, user_photos_only=user_photos_only)

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
        shuffle = not args.no_shuffle
        client.cycle_images(period=args.period, user_photos_only=user_photos_only, shuffle=shuffle)

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


if __name__ == "__main__":
    sys.exit(main())
