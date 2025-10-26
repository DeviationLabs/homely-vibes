#!/usr/bin/env python3
from abc import ABC, abstractmethod
from typing import List, TYPE_CHECKING
import argparse
import re
import sys
import time
import traceback
from lib import Constants
from lib.logger import SystemLogger
from lib import Mailer
from lib import NetHelpers
from lib.MyPushover import Pushover

if TYPE_CHECKING:
    pass

logger = SystemLogger.get_logger(__name__)


class Node(ABC):
    def __init__(self, name: str, ip: str, pushover: Pushover):
        self.name = name
        self.ip = ip
        self.pushover = pushover
        self.is_online = False

    def check_state(self, desired_up: bool = True, attempts: int = 5) -> bool:
        """Check if node is in desired state (up/down) - used for reboot verification"""
        for attempt in range(attempts):
            current_state = NetHelpers.ping_output(node=self.ip, desired_up=desired_up)
            logger.debug(
                f"{attempt=} for {self.name}, {desired_up=} In desired state: {current_state}"
            )
            if current_state == desired_up:
                self.is_online = current_state if desired_up else not current_state
                return True
            time.sleep(1)
        self.is_online = False if desired_up else True
        return False

    def heartbeat(self) -> bool:
        """Base health check - ping test. Subclasses should call super() then add specific checks"""
        self.is_online = NetHelpers.ping_output(node=self.ip, desired_up=True)
        logger.debug(f"Ping check for {self.name}: {self.is_online}")
        return self.is_online

    @abstractmethod
    def reboot_node(self) -> str:
        """Reboot the node and return status message"""
        pass


class FoscamNode(Node):
    def __init__(self, name: str, config: Constants.NodeConfig, pushover: Pushover):
        super().__init__(name, config.ip, pushover)
        self.config = config

    def reboot_node(self) -> str:
        """Reboot Foscam camera via HTTP API"""
        cmd = "http://%s:88//cgi-bin/CGIProxy.fcgi?cmd=rebootSystem&usr=%s&pwd=%s" % (
            self.ip,
            self.config.username,
            self.config.password,
        )
        try:
            msg = str(NetHelpers.http_req(cmd))
            logger.info(f"Rebooted foscam node: {self.name}")
            return msg
        except OSError as e:
            err_msg = getattr(e, "message", repr(e))
            msg = f">> ERROR: When rebooting {self.name}. Got {err_msg[:100]}..."
            logger.error(msg)
            return msg

    def heartbeat(self) -> bool:
        """Check Foscam health: ping + image capture"""
        # First do base ping check
        if not super().heartbeat():
            return False

        # Then do Foscam-specific image capture test
        from lib.FoscamImager import FoscamImager

        MAX_COUNT = 2
        for _ in range(MAX_COUNT):
            try:
                myCam = FoscamImager(self.ip, False)
                if myCam.getImage() is not None:
                    logger.info(f"Got image from node: {self.name}")
                    return True
            except Exception:
                temp = "\n%s" % traceback.format_exc()
                logger.error(temp)
                time.sleep(30)

        logger.error(f"Got image, but failed to preview from: {self.name}")
        self.pushover.send_message(
            f"Foscam node {self.name} cannot capture image",
            title="Foscam Health Check Failed",
        )
        return False


class WindowsNode(Node):
    def __init__(self, name: str, config: Constants.NodeConfig, pushover: Pushover):
        super().__init__(name, config.ip, pushover)
        self.config = config

    def reboot_node(self) -> str:
        """Reboot Windows machine via SSH"""
        winCmd = 'cmd /c "shutdown /r /f & ping localhost -n 3 > nul"'
        return str(NetHelpers.ssh_cmd(self.ip, self.config.username, self.config.password, winCmd))

    def heartbeat(self) -> bool:
        """Check Windows health: ping + uptime statistics"""
        # First do base ping check
        if not super().heartbeat():
            return False

        # Then do Windows-specific uptime check
        winCmd = "net statistics workstation"
        output = str(
            NetHelpers.ssh_cmd(self.ip, self.config.username, self.config.password, winCmd)
        )
        if "successful" in output:
            match = re.search("Statistics since (.*)", output)
            if match:
                foundStr = match.group(1)
                logger.info(f"{self.name} is up since {foundStr}")
                return True
        return False


class NodeChecker:
    def __init__(self, mode: str):
        self.mode = mode
        self.pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS["NodeCheck"])
        self.nodes: List[Node] = []
        self.messages: List[str] = []

        # Create nodes based on mode
        for name, config in Constants.NODE_CONFIGS.items():
            if mode == "foscam" and config.node_type == "foscam":
                self.nodes.append(FoscamNode(name, config, self.pushover))
            elif mode == "windows" and config.node_type == "windows":
                self.nodes.append(WindowsNode(name, config, self.pushover))

    def log_message(self, msg: str) -> None:
        """Log message and add to report"""
        logger.info(msg)
        self.messages.append(msg)

    def check_connectivity(self) -> bool:
        """Check connectivity of all nodes"""
        self.log_message("Checking connectivity...")
        all_healthy = True

        for node in self.nodes:
            if node.heartbeat():
                self.log_message(f"   {self.mode}: {node.name} online.")
            else:
                self.log_message(f">> ERROR {self.mode}: {node.name} offline.")
                self.pushover.send_message(
                    f"{self.mode.title()} node {node.name} is offline",
                    title="Node Check Failed",
                )
                all_healthy = False

        return all_healthy

    def reboot_nodes(self) -> bool:
        """Reboot all nodes and verify they come back online"""
        self.log_message("Rebooting now...")

        # Reboot all nodes
        for node in self.nodes:
            if isinstance(node, WindowsNode):
                # Do deep check before rebooting Windows nodes
                node.heartbeat()
            result = node.reboot_node()
            logger.debug(result)

        # Wait for nodes to go down
        self.log_message("Waiting for nodes to go down...")
        for node in self.nodes:
            if node.check_state(desired_up=False, attempts=180):
                self.log_message(f"   Confirmed node is down: {node.name}")
            else:
                self.log_message(f">> ERROR: Oops! Node did not reboot: {node.name}")
                self.pushover.send_message(
                    f"{self.mode.title()} node {node.name} failed to reboot",
                    title="Node Reboot Failed",
                )

        # Wait for nodes to come back up
        self.log_message("Sleep until nodes restart...")
        all_recovered = True
        for node in self.nodes:
            if node.check_state(desired_up=True, attempts=180):
                self.log_message(f"   {self.mode}: {node.name} back online.")
            else:
                self.log_message(f">> ERROR: {self.mode}: {node.name} failed online.")
                self.pushover.send_message(
                    f"{self.mode.title()} node {node.name} failed to come back online after reboot",
                    title="Node Recovery Failed",
                )
                all_recovered = False

        time.sleep(60)  # Wait for nodes to stabilize
        return all_recovered

    def generate_report(self, system_healthy: bool, always_email: bool = False) -> None:
        """Generate and send final report"""
        if not system_healthy:
            self.log_message(">> ERROR: Node check failed!")
            failed_nodes = [node.name for node in self.nodes if not node.is_online]
            self.pushover.send_message(
                f"{self.mode.title()} Node check failed for {', '.join(failed_nodes)}",
                title="Node Check",
                priority=1,
            )
        else:
            self.log_message("All is well")

        Mailer.sendmail(
            topic=f"[NodeCheck-{self.mode}]",
            alert=not system_healthy,
            message="\n".join(self.messages),
            always_email=always_email,
        )

    def heartbeat_check(self) -> bool:
        """Perform heartbeat check on all nodes"""
        self.log_message("Performing heartbeat checks...")
        all_healthy = True

        for node in self.nodes:
            if node.heartbeat():
                self.log_message(f"   {self.mode}: {node.name} healthy.")
            else:
                self.log_message(f">> ERROR {self.mode}: {node.name} unhealthy.")
                self.pushover.send_message(
                    f"{self.mode.title()} node {node.name} failed heartbeat check",
                    title="Node Heartbeat Failed",
                )
                all_healthy = False

        return all_healthy


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
        "--reboot",
        help="Reboot or check only",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--display_image",
        help="Display captured image",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--always_email",
        help="Send email report",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--heartbeat",
        help="Perform heartbeat check only (no reboot)",
        action="store_true",
        default=False,
    )
    parser.add_argument("-d", "--debug", action="store_true", help="set logging level to debug")
    args = parser.parse_args()

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    # Initialize node checker
    checker = NodeChecker(args.mode)

    # Handle different operation modes
    if args.heartbeat:
        # Heartbeat check only
        system_healthy = checker.heartbeat_check()
    else:
        # Full connectivity check (includes heartbeat checks)
        connectivity_ok = checker.check_connectivity()
        system_healthy = connectivity_ok

        # Reboot if requested
        if args.reboot:
            reboot_ok = checker.reboot_nodes()
            system_healthy = system_healthy and reboot_ok

            # Re-check health after reboot
            final_health = checker.check_connectivity()
            system_healthy = system_healthy and final_health

    # Generate final report
    checker.generate_report(system_healthy, args.always_email)
    print("Done!")
