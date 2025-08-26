#!/usr/bin/env python3
import argparse
import re
import sys
import time
import traceback
from lib import Constants
from lib.logger import SystemLogger
import FoscamImager
import Mailer
import NetHelpers

logger = SystemLogger.get_logger(__name__)

system_healthy = True
state = dict()
message = ""

#### Helper Functions ####


def reboot_foscam(nodeName):
    node = Constants.FOSCAM_NODES[nodeName]
    cmd = "http://%s:88//cgi-bin/CGIProxy.fcgi?cmd=rebootSystem&usr=%s&pwd=%s" % (
        node,
        Constants.FOSCAM_USERNAME,
        Constants.FOSCAM_PASSWORD,
    )
    try:
        msg = NetHelpers.http_req(cmd)
    except OSError as e:
        err_msg = getattr(e, "message", repr(e))
        msg = ">> ERROR: When rebooting %s. Got %s..." % (nodeName, err_msg[:100])
        log_message(msg)
    return msg


def reboot_windows(node):
    # Ping to keep child proc alive for long enough
    winCmd = "shutdown /r /f ; ping localhost -n 3 > nul"
    return NetHelpers.ssh_cmd(
        node, Constants.WINDOWS_USERNAME, Constants.WINDOWS_PASSWORD, winCmd
    )


# Note: For windows nodes only
def print_deep_state(nodeName):
    node = Constants.WINDOWS_NODES[nodeName]
    winCmd = "net statistics workstation"
    output = NetHelpers.ssh_cmd(
        node, Constants.WINDOWS_USERNAME, Constants.WINDOWS_PASSWORD, winCmd
    )
    if "successful" in output:
        foundStr = re.search("Statistics since (.*)", output).group(1)
        output = "%s is up since %s" % (nodeName, foundStr)
    return output


# Note: For Foscam nodes only
def check_if_can_image(nodeName, display_image):
    MAX_COUNT = 2
    count = 0
    while count < MAX_COUNT:
        count += 1
        try:
            myCam = FoscamImager.FoscamImager(
                Constants.FOSCAM_NODES[nodeName], display_image
            )
            if myCam.getImage() is not None:
                log_message("   Got image from node: %s" % nodeName)
                if display_image:
                    print("Displaying %s ..." % nodeName)
                    time.sleep(5)
                return True
        except Exception:
            temp = "\n%s" % traceback.format_exc()
            logger.error(temp)
            time.sleep(30)
    log_message(">> ERROR: Got image, but failed to preview from: %s" % nodeName)
    return False


def log_message(msg):
    global message
    logger.info(msg)
    message += msg + "\n"


def check_state(desired_up, attempts):
    global state
    global system_healthy  # We do something strange here with global state. Do not touch
    for nodeName, nodeIP in nodes.items():
        state[nodeName] = False
    for attempt in range(attempts):
        logger.debug(f"{state.values()=}")
        if all(state.values()):
            return
        time.sleep(1)
        for nodeName, nodeIP in nodes.items():
            # if state is false, then ping again to check if state is now true
            if not state[nodeName]:
                state[nodeName] = NetHelpers.ping_output(
                    node=nodeIP, desired_up=desired_up
                )
                logger.debug(
                    f"{attempt=} for {nodeName}, {desired_up=} In desired state: {state[nodeName]}"
                )
    else:
        system_healthy = False


#### Main Routine ####
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reboot Utility")
    parser.add_argument(
        "--mode",
        help="Foscams or Windows(i.e.:Alpha)",
        choices=["foscam", "windows"],
        default="foscam",
    )
    parser.add_argument(
        "--reboot", help="Reboot or check only", action="store_true", default=False
    )
    parser.add_argument(
        "--display_image",
        help="Display captured image",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--always_email", help="Send email report", action="store_true", default=False
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="set logging level to debug"
    )
    args = parser.parse_args()

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    nodes = Constants.FOSCAM_NODES if args.mode == "foscam" else Constants.WINDOWS_NODES

    log_message("Checking connectivity...")
    check_state(
        desired_up=True, attempts=5
    )  ## Seeing intermittent nwk failures. Let's mask these
    for nodeName, nodeIP in nodes.items():
        if state[nodeName]:
            log_message("   %s: %s online." % (args.mode, nodeName))
        else:
            log_message(">> ERROR %s: %s offline." % (args.mode, nodeName))

    if args.reboot:
        log_message("Rebooting now...")
        for nodeName, nodeIP in nodes.items():
            if args.mode == "foscam":
                logger.debug(reboot_foscam(nodeName))
            else:
                # If windows and alive, do a deep check before rebooting.
                log_message(print_deep_state(nodeName))
                logger.debug(reboot_windows(nodeIP))
        check_state(desired_up=False, attempts=180)
        for nodeName, nodeIP in nodes.items():
            if state[nodeName]:
                log_message("   Confirmed node is down: %s" % nodeName)
            else:
                log_message(">> ERROR: Oops! Node did not reboot: %s" % nodeName)
        log_message("Sleep until nodes restart...")
        check_state(desired_up=True, attempts=180)
        for nodeName, nodeIP in nodes.items():
            if state[nodeName]:
                log_message("   %s: %s back online." % (args.mode, nodeName))
            else:
                log_message(">> ERROR: %s: %s failed online." % (args.mode, nodeName))
        time.sleep(60)  # generously wait for nodes to stabilize

    # Do a deeper check
    log_message("Check if foscams are healthy...")
    for nodeName, nodeIP in nodes.items():
        if state[nodeName]:
            if args.mode == "foscam":
                node_healthy = check_if_can_image(nodeName, args.display_image)
                system_healthy = system_healthy and node_healthy
            else:
                # If windows and alive, do a deep check
                log_message(print_deep_state(nodeName))

    # Cleanup and reporting
    if not system_healthy:
        log_message(">> ERROR: Node check failed!")
    else:
        log_message("All is well")
    Mailer.sendmail(
        topic="[NodeCheck-%s]" % args.mode,
        alert=not system_healthy,
        message=message,
        always_email=args.always_email,
    )
    print("Done!")
