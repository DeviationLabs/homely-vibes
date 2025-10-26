#!/usr/bin/env python3
from typing import List, TYPE_CHECKING
import argparse
import sys
import time
from lib import Constants
from lib.logger import SystemLogger
from lib import Mailer
from lib.MyPushover import Pushover
from .nodes import Node, FoscamNode, WindowsNode

if TYPE_CHECKING:
    pass

logger = SystemLogger.get_logger(__name__)


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
        time.sleep(60)  # Wait for nodes to stabilize
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

    def heartbeat_check(self, specific_nodes: List[str] | None = None) -> bool:
        """Perform heartbeat check on specified nodes or all nodes"""
        if specific_nodes:
            # Filter nodes to only check specified ones
            nodes_to_check = [node for node in self.nodes if node.name in specific_nodes]
            if not nodes_to_check:
                self.log_message(
                    f">> ERROR: No matching nodes found for: {', '.join(specific_nodes)}"
                )
                return False

            # Check if any specified nodes don't exist
            found_names = {node.name for node in nodes_to_check}
            missing_nodes = set(specific_nodes) - found_names
            if missing_nodes:
                self.log_message(f">> WARNING: Nodes not found: {', '.join(missing_nodes)}")

            self.log_message(f"Performing heartbeat checks on: {', '.join(found_names)}...")
        else:
            nodes_to_check = self.nodes
            self.log_message("Performing heartbeat checks on all nodes...")

        all_healthy = True

        for node in nodes_to_check:
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
    parser.add_argument(
        "--nodes",
        help="Specific nodes to check (use with --heartbeat). If omitted, checks all nodes",
        nargs="*",
        metavar="NODE_NAME",
    )
    parser.add_argument("-d", "--debug", action="store_true", help="set logging level to debug")
    args = parser.parse_args()

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    # Validate arguments
    if args.nodes and not args.heartbeat:
        print("Error: --nodes can only be used with --heartbeat")
        sys.exit(1)

    # Initialize node checker
    checker = NodeChecker(args.mode)

    # Handle different operation modes
    if args.heartbeat:
        # Heartbeat check only
        system_healthy = checker.heartbeat_check(args.nodes)
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
