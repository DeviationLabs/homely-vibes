#!/usr/bin/env python3
import argparse
import os
import sys
import time
from pathlib import Path
from lib.config import get_config
from lib.logger import SystemLogger
from lib import Mailer
from lib.MyPushover import Pushover

cfg = get_config()
logger = SystemLogger.get_logger(__name__)

# Initialize Pushover client for Foscam notifications
pushover = Pushover(cfg.pushover.user, cfg.pushover.tokens["NodeCheck"])


def purge_old_foscam_files() -> tuple[bool, str]:
    """Purge old foscam files with integrated functionality from shell script."""
    success = True
    messages = []

    # Configuration from config
    cfg = get_config()
    purge_after_days = cfg.node_check.purge_after_days
    foscam_dir = cfg.node_check.foscam_dir

    messages.append("Starting foscam file purge process...")

    # Check if foscam directory is mounted/accessible
    foscam_path = Path(foscam_dir)
    if not foscam_path.exists() or not foscam_path.is_dir():
        error_msg = f"Error: Foscam directory {foscam_dir} is not accessible"
        messages.append(error_msg)
        logger.error(error_msg)
        return False, "\n".join(messages)

    messages.append(f"Foscam directory {foscam_dir} is accessible")

    # Change to foscam directory
    original_cwd = os.getcwd()
    try:
        os.chdir(foscam_dir)

        # Delete files older than purge_after_days
        step_msg = f"Deleting all IPCam data older than {purge_after_days} days..."
        messages.append(step_msg)

        try:
            # Use pathlib to find and remove old files (Pythonic approach)
            current_time = time.time()
            cutoff_time = current_time - (
                purge_after_days * 24 * 60 * 60
            )  # Convert days to seconds

            deleted_count = 0
            error_count = 0

            # Walk through directories at depth >= 2 (mindepth 2 equivalent)
            for file_path in Path(".").rglob("*"):
                # Skip if not a file or if depth < 2
                if not file_path.is_file() or len(file_path.parts) < 3:
                    continue

                try:
                    # Check file modification time
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()  # Remove the file
                        deleted_count += 1
                except (OSError, PermissionError) as e:
                    error_count += 1
                    logger.warning(f"Could not delete {file_path}: {e}")

            # Report cleaning results prominently
            if deleted_count == 0:
                messages.append("No old files found to clean")
                pushover_msg = (
                    f"Foscam cleanup: No old files to clean (older than {purge_after_days} days)"
                )
            elif error_count == 0:
                messages.append(f"✓ Successfully cleaned {deleted_count} old files")
                logger.info(f"Foscam cleanup: {deleted_count} files removed, 0 errors")
                pushover_msg = f"✓ Foscam cleanup: Successfully removed {deleted_count} old files"
            else:
                messages.append(f"⚠ Cleaned {deleted_count} old files with {error_count} errors")
                logger.warning(
                    f"Foscam cleanup: {deleted_count} files removed, {error_count} errors"
                )
                pushover_msg = (
                    f"⚠ Foscam cleanup: Removed {deleted_count} files with {error_count} errors"
                )
                if (
                    error_count > deleted_count * 0.1
                ):  # If errors > 10% of deletions, flag as failure
                    success = False
        except Exception as e:
            error_msg = f"Error during file deletion: {str(e)}"
            messages.append(error_msg)
            logger.error(error_msg)
            success = False
            pushover_msg = f"Error during file deletion: {str(e)}"

    finally:
        # Restore original working directory
        pushover.send_message(pushover_msg, title="Foscam Cleanup")
        os.chdir(original_cwd)

    return success, "\n".join(messages)


#### Main Routine ####
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge Foscam videos from NAS")
    parser.add_argument(
        "--always_email",
        help="Send email report",
        action="store_true",
        default=False,
    )
    args = parser.parse_args()

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    # Run the integrated purge functionality
    alert = False
    try:
        success, msg = purge_old_foscam_files()
        alert = not success
    except Exception as e:
        msg = f"Fatal error in foscam purge: {str(e)}"
        alert = True
        logger.error(msg)
    finally:
        logger.info(msg)

    Mailer.sendmail(
        topic="[PurgeFoscam]",
        alert=alert,
        message=msg,
        always_email=args.always_email,
    )
    print("Done!")
