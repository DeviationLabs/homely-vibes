#!/usr/bin/env python3
"""
Network Speed Test Utility

Performs network speed tests using the speedtest-cli tool and reports results
via email and pushover notifications. Supports retry logic for unreliable connections.
"""

import argparse
import json
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from lib import Constants
from lib import Mailer
from lib.logger import SystemLogger
from lib.MyPushover import Pushover

logger = SystemLogger.get_logger(__name__)
pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS['NetworkCheck'])

# Constants
SPEEDTEST_CMD = "/usr/bin/speedtest"
SPEEDTEST_TIMEOUT = 600


@dataclass
class SpeedTestResult:
    """Container for speed test results."""
    download_mbps: float
    upload_mbps: float
    external_ip: str
    is_good: bool
    is_degraded: bool
    message: str


def parse_speedtest_output(output: str) -> Dict:
    """
    Parse speedtest JSON output to extract result data.
    
    Args:
        output: Raw speedtest command output
        
    Returns:
        Dictionary containing the result data
        
    Raises:
        ValueError: If no valid result found in output
    """
    lines = output.strip().split("\n")
    result_lines = [
        line for line in lines 
        if line and json.loads(line).get("type") == "result"
    ]
    
    if not result_lines:
        raise ValueError("No result found in speedtest output")
        
    return json.loads(result_lines[0])


def run_speedtest() -> Tuple[Optional[SpeedTestResult], str]:
    """
    Execute speedtest command and parse results.
    
    Returns:
        Tuple of (SpeedTestResult or None, raw_message)
    """
    try:
        output = subprocess.check_output(
            [SPEEDTEST_CMD, "-f", "json"],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=SPEEDTEST_TIMEOUT,
        )
        
        payload = parse_speedtest_output(output)
        
        # Convert bandwidth from bytes/s to Mbps (bytes * 8 bits/byte / 1024^2 = Mbps)
        BYTES_TO_MBPS = 8 / (1024 * 1024)
        download_mbps = payload.get("download", {}).get("bandwidth", 0) * BYTES_TO_MBPS
        upload_mbps = payload.get("upload", {}).get("bandwidth", 0) * BYTES_TO_MBPS
        external_ip = payload.get("interface", {}).get("externalIp", "UNK")
        
        # Determine connection quality
        is_good = (download_mbps > Constants.MIN_DL_BW and 
                  upload_mbps > Constants.MIN_UL_BW)
        is_degraded = (download_mbps > Constants.MIN_DL_BW * 0.8 and 
                      upload_mbps > Constants.MIN_UL_BW * 0.8)
        
        if is_good:
            status = "Link good"
        elif is_degraded:
            status = "Link degraded (>80%)"
        else:
            status = "Link bad (<80%)"
            
        message = f"{status}: [{external_ip}] DL: {download_mbps:.1f} Mbps UL: {upload_mbps:.1f} Mbps"
        
        result = SpeedTestResult(
            download_mbps=download_mbps,
            upload_mbps=upload_mbps,
            external_ip=external_ip,
            is_good=is_good,
            is_degraded=is_degraded,
            message=message
        )
        
        return result, message
        
    except Exception as e:
        error_msg = f"Speedtest failed: {e}"
        logger.error(error_msg)
        return None, error_msg


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Network Speed Test and External IP detection utility"
    )
    parser.add_argument(
        "--always_email", 
        help="Send email report", 
        action="store_true", 
        default=False
    )
    parser.add_argument(
        "--max_retries", 
        help="Retry if low score on first try", 
        type=int, 
        default=1
    )
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info(f"Started: {' '.join(sys.argv)}")

    alert = True
    attempt = 0
    all_messages = []
    
    while alert and attempt < args.max_retries:
        attempt += 1
        logger.info(f"Speed test attempt {attempt}/{args.max_retries}")
        
        result, message = run_speedtest()
        
        print(message)
        logger.info(message)
        all_messages.append(message)
        
        if result and result.is_good:
            alert = False
            logger.info("Speed test passed - connection is good")
            break
        elif result and result.is_degraded:
            logger.warning("Speed test shows degraded connection")
        else:
            logger.error("Speed test shows poor connection or failed")
            
        # Wait before retry (except on last attempt)
        if alert and attempt < args.max_retries:
            logger.info("Waiting 1 minute before retry...")
            time.sleep(60)

    # Prepare final message
    aggregate_message = "\n".join(all_messages)
    final_message = all_messages[-1] if all_messages else "No speed test results"
    
    # Send notifications
    Mailer.sendmail(
        topic="[SpeedTest]",
        message=aggregate_message,
        always_email=args.always_email,
        alert=alert,
    )
    
    pushover.send_message(final_message, title="SpeedTest")
    
    logger.info("Speed test completed")


if __name__ == "__main__":
    main()
