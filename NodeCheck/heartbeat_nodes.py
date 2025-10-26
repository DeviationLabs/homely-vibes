#!/usr/bin/env python3
import argparse
import sys
import time
from typing import List, Set
from lib import Constants
from lib.logger import SystemLogger
from lib.MyPushover import Pushover
from NodeCheck.nodes import Node, FoscamNode, WindowsNode, GenericNode

logger = SystemLogger.get_logger(__name__)


class HeartbeatMonitor:
    def __init__(self, specific_nodes: Set[str] | None = None) -> None:
        self.specific_nodes = {node.lower() for node in specific_nodes} if specific_nodes else None
        self.pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS["NodeCheck"])
        
        self.monitored_nodes = self._create_nodes_list()
        
        self.last_down_nodes: Set[str] = set()
        self.last_notification_time: float | None = None
        
    def _create_nodes_list(self) -> List[Node]:
        """Create nodes for all node types and filter based on specific_nodes parameter"""
        nodes = []
        
        for name, config in Constants.NODE_CONFIGS.items():
            if config.node_type == "foscam":
                nodes.append(FoscamNode(name, config))
            elif config.node_type == "windows":
                nodes.append(WindowsNode(name, config))
            elif config.node_type == "generic":
                nodes.append(GenericNode(name, config))
        
        if self.specific_nodes:
            available_node_names = {node.name.lower() for node in nodes}
            requested_set = self.specific_nodes
            missing_nodes = requested_set - available_node_names

            if missing_nodes:
                raise ValueError(f"Requested nodes not found: {', '.join(missing_nodes)}")

            # Filter to only include existing requested nodes (case-insensitive)
            nodes = [node for node in nodes if node.name.lower() in requested_set]

            if not nodes:
                raise ValueError(
                    f"No valid nodes found from requested: {', '.join(self.specific_nodes)}"
                )

            logger.info(
                f"Monitoring specific nodes: {', '.join([node.name for node in nodes])}"
            )
        else:
            logger.info(
                f"Monitoring all nodes: {', '.join([node.name for node in nodes])}"
            )
        
        return nodes

    def check_monitored_nodes(self) -> Set[str]:
        """Check all monitored nodes and return set of down node names"""
        down_nodes = set()

        for node in self.monitored_nodes:
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
            title = "Node Down"
            message = f"Node {node_list} is down"
        else:
            title = "Nodes Down"
            message = f"{count} nodes are down: {node_list}"

        self.pushover.send_message(
            message,
            title=title,
            priority=1,  # High priority
        )
        self.last_notification_time = time.time()
        logger.info(f"Sent notification: {message}")

    def run_continuous_monitoring(self, poll_time: int, cooloff_time: int) -> None:
        """Run continuous heartbeat monitoring"""
        logger.info(f"Starting continuous heartbeat monitoring (poll interval: {poll_time}s)")

        try:
            while True:
                logger.debug("Performing heartbeat check cycle...")
                current_down_nodes = self.check_monitored_nodes()

                # Only send notification if nodes are currently down
                # (regardless of previous state - this ensures we get notified of ongoing issues)
                if current_down_nodes:
                    # Send notification if we have new down nodes or if enough time has passed since last notification
                    should_notify = (current_down_nodes != self.last_down_nodes or 
                                   self.last_notification_time is None or 
                                   time.time() - self.last_notification_time > cooloff_time * 60)
                    if should_notify:
                        self.send_notification(current_down_nodes)
                    else:
                        logger.debug(f"Same nodes still down: {', '.join(current_down_nodes)}")
                else:
                    if self.last_down_nodes:
                        logger.info("All nodes are now healthy (recovery detected)")
                    logger.debug("All nodes healthy")

                self.last_down_nodes = current_down_nodes

                logger.debug(f"Sleeping for {poll_time} seconds...")
                time.sleep(poll_time)

        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user (Ctrl+C)")
        except Exception as e:
            logger.error(f"Monitoring failed with error: {e}")
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous Node Heartbeat Monitor")
    parser.add_argument(
        "--poll",
        help="Polling interval in seconds",
        type=int,
        default=3600,
    )
    parser.add_argument(
        "--cooloff",
        help="Cooloff time in minutes",
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
        monitor = HeartbeatMonitor(args.nodes)

        # Start continuous monitoring
        monitor.run_continuous_monitoring(poll_time=args.poll, cooloff_time=args.cooloff)

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
