#!/usr/bin/env python3
import argparse
import sys
import time
from typing import List, Set
from lib import Constants
from lib.logger import SystemLogger
from lib.MyPushover import Pushover
from NodeCheck.check_nodes import NodeChecker

logger = SystemLogger.get_logger(__name__)


class HeartbeatMonitor:
    def __init__(self, mode: str, poll_time: int, specific_nodes: List[str] | None = None):
        self.mode = mode
        self.poll_time = poll_time
        self.specific_nodes = specific_nodes
        self.pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS["NodeCheck"])
        self.checker = NodeChecker(mode)
        self.last_down_nodes: Set[str] = set()

        # Filter nodes if specific ones requested
        if specific_nodes:
            available_nodes = {node.name for node in self.checker.nodes}
            requested_set = set(specific_nodes)
            missing_nodes = requested_set - available_nodes

            if missing_nodes:
                logger.warning(f"Requested nodes not found: {', '.join(missing_nodes)}")

            # Filter to only include existing requested nodes
            self.checker.nodes = [node for node in self.checker.nodes if node.name in requested_set]

            if not self.checker.nodes:
                raise ValueError(
                    f"No valid nodes found from requested: {', '.join(specific_nodes)}"
                )

            logger.info(
                f"Monitoring specific nodes: {', '.join([node.name for node in self.checker.nodes])}"
            )
        else:
            logger.info(
                f"Monitoring all {mode} nodes: {', '.join([node.name for node in self.checker.nodes])}"
            )

    def check_all_nodes(self) -> Set[str]:
        """Check all monitored nodes and return set of down node names"""
        down_nodes = set()

        for node in self.checker.nodes:
            try:
                if not node.heartbeat():
                    down_nodes.add(node.name)
                    logger.warning(f"Node {node.name} is down")
                else:
                    logger.debug(f"Node {node.name} is healthy")
            except Exception as e:
                logger.error(f"Error checking node {node.name}: {e}")
                down_nodes.add(node.name)

        return down_nodes

    def send_notification(self, down_nodes: Set[str]) -> None:
        """Send pushover notification for down nodes"""
        if not down_nodes:
            return

        node_list = ", ".join(sorted(down_nodes))
        count = len(down_nodes)

        if count == 1:
            title = f"{self.mode.title()} Node Down"
            message = f"Node {node_list} is down"
        else:
            title = f"{self.mode.title()} Nodes Down"
            message = f"{count} nodes are down: {node_list}"

        self.pushover.send_message(
            message,
            title=title,
            priority=1,  # High priority
        )
        logger.info(f"Sent notification: {message}")

    def run_continuous_monitoring(self) -> None:
        """Run continuous heartbeat monitoring"""
        logger.info(f"Starting continuous heartbeat monitoring (poll interval: {self.poll_time}s)")

        try:
            while True:
                logger.debug("Performing heartbeat check cycle...")
                current_down_nodes = self.check_all_nodes()

                # Only send notification if nodes are currently down
                # (regardless of previous state - this ensures we get notified of ongoing issues)
                if current_down_nodes:
                    # Send notification if we have new down nodes or if this is a new check cycle
                    if current_down_nodes != self.last_down_nodes:
                        self.send_notification(current_down_nodes)
                    else:
                        logger.debug(f"Same nodes still down: {', '.join(current_down_nodes)}")
                else:
                    if self.last_down_nodes:
                        logger.info("All nodes are now healthy (recovery detected)")
                    logger.debug("All nodes healthy")

                self.last_down_nodes = current_down_nodes

                logger.debug(f"Sleeping for {self.poll_time} seconds...")
                time.sleep(self.poll_time)

        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Monitoring failed with error: {e}")
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous Node Heartbeat Monitor")
    parser.add_argument(
        "--mode",
        help="Node type to monitor",
        choices=["foscam", "windows"],
        default="foscam",
    )
    parser.add_argument(
        "--poll",
        help="Polling interval in seconds",
        type=int,
        default=3600,
    )
    parser.add_argument(
        "--nodes",
        help="Specific nodes to monitor. If omitted, monitors all nodes of the specified type",
        nargs="*",
        metavar="NODE_NAME",
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel("DEBUG")

    logger.info("============")
    logger.info("Invoked command: %s" % " ".join(sys.argv))

    # Validate poll time
    if args.poll < 10:
        print("Error: --poll must be at least 10 seconds")
        sys.exit(1)

    try:
        # Initialize monitor
        monitor = HeartbeatMonitor(args.mode, args.poll, args.nodes)

        # Start continuous monitoring
        monitor.run_continuous_monitoring()

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
