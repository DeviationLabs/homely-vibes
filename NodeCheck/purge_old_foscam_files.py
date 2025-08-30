#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
from pathlib import Path
from lib.logger import SystemLogger
from lib import Mailer
from lib import Constants

logger = SystemLogger.get_logger(__name__)


def purge_old_foscam_files():
    """Purge old foscam files with integrated functionality from shell script."""
    success = True
    messages = []
    
    # Configuration from Constants
    purge_after_days = getattr(Constants, 'PURGE_AFTER_DAYS', 30)
    foscam_dir = getattr(Constants, 'FOSCAM_DIR', '/path/to/foscam')
    
    messages.append(f"Starting foscam file purge process...")
    
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
            # Use find command to locate and remove old files
            find_cmd = [
                'find', '.', '-mindepth', '2', '-type', 'f', 
                '-mtime', f'+{purge_after_days}', '-delete'
            ]
            result = subprocess.run(find_cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode == 0:
                messages.append("File deletion completed successfully")
            else:
                error_msg = f"Error during file deletion: {result.stderr}"
                messages.append(error_msg)
                logger.error(error_msg)
                success = False
                
        except subprocess.TimeoutExpired:
            error_msg = "File deletion timed out after 5 minutes"
            messages.append(error_msg)
            logger.error(error_msg)
            success = False
        except Exception as e:
            error_msg = f"Error during file deletion: {str(e)}"
            messages.append(error_msg)
            logger.error(error_msg)
            success = False
            
    finally:
        # Restore original working directory
        os.chdir(original_cwd)
    
    if success:
        messages.append("Foscam file purge completed successfully")
    else:
        messages.append("Foscam file purge encountered errors")
    
    return success, "\n".join(messages)


#### Main Routine ####
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge Foscam videos from NAS")
    parser.add_argument(
        "--always_email", help="Send email report", action="store_true", default=False
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
        topic="[PurgeFoscam]", alert=alert, message=msg, always_email=args.always_email
    )
    print("Done!")
