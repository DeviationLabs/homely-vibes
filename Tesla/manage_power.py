#!/usr/bin/env python3
"""Clean Tesla Powerwall management system."""

import argparse
import sys
import time
from dataclasses import dataclass
from typing import List, Optional
import importlib
from lib import Constants
from lib.MyPushover import Pushover
from lib.TeslaPy.teslapy import Tesla as TeslaClient
from lib.logger import get_logger


@dataclass
class DecisionPoint:
    """Represents a decision point for power management."""

    time_start: int
    time_end: int
    pct_thresh: float
    pct_gradient_per_hr: float
    iff_higher: bool
    op_mode: str
    pct_min: float
    pct_min_trail_stop: Optional[float]
    reason: str
    always_notify: bool = False


class BatteryHistory:
    """Manages battery percentage history and extrapolation."""

    MAX_HISTORY = 5

    def __init__(self):
        self.percentages: List[float] = []

    def add_percentage(self, pct: float) -> None:
        """Add a percentage to history, maintaining max size."""
        self.percentages.insert(0, pct)
        if len(self.percentages) > self.MAX_HISTORY:
            self.percentages.pop()

    def get_average_gradient(self) -> float:
        """Calculate average gradient from history."""
        if len(self.percentages) < 2:
            return 0.0

        diffs = [
            self.percentages[i] - self.percentages[i + 1]
            for i in range(len(self.percentages) - 1)
        ]
        return sum(diffs) / len(diffs) if diffs else 0.0

    def extrapolate(self, time_sampling: float = 1.0) -> Optional[float]:
        """
        Extrapolate next percentage based on history.
        time_sampling is in minutes.
        """
        if not self.percentages:
            return None

        avg_gradient = self.get_average_gradient()
        return round(self.percentages[0] + avg_gradient * time_sampling, 2)


class PowerwallManager:
    """Manages Tesla Powerwall operations."""

    def __init__(self, email: str, send_notifications: bool = False):
        self.email = email
        self.send_notifications = send_notifications
        self.battery_history = BatteryHistory()
        self.loop_count = 0
        self.fail_count = 0
        self.cached_op_mode = (
            None  # APB: 5/25/23 seems we are no longer getting this data from the query
        )
        self.logger = get_logger(__name__)
        self.pushover = Pushover(
            Constants.PUSHOVER_USER, Constants.PUSHOVER_TOKENS["Powerwall"]
        )

    def sanitize_battery_percentage(self, pct: float, time_sampling: float) -> float:
        """Sanitize battery percentage using history and extrapolation."""
        pct = round(pct, 2)
        original_pct = pct

        # Check for bad data
        if len(self.battery_history.percentages) >= BatteryHistory.MAX_HISTORY and (
            pct <= 0 or pct in self.battery_history.percentages
        ):
            extrapolated = self.battery_history.extrapolate(time_sampling)
            if extrapolated is not None:
                pct = max(min(extrapolated, 100), 0)
                pct = round(pct, 2)

        # Add to history (use original if non-zero, otherwise sanitized)
        self.battery_history.add_percentage(original_pct if original_pct != 0 else pct)

        if abs(pct - original_pct) > 0.5:
            self.logger.warning(
                f"Bad battery data: {original_pct}% -> {pct}% "
                f"from history {self.battery_history.percentages}"
            )
            return pct

        return original_pct

    def evaluate_condition(
        self, current: float, threshold: float, direction_up: bool
    ) -> bool:
        """Evaluate if condition matches for triggering action."""
        if direction_up:
            return current > threshold
        else:
            return current < threshold

    def get_powerwall_data(self, product) -> dict:
        """Fetch and validate powerwall data."""
        product.get_site_info()
        product.get_site_data()

        # Validate configuration
        can_export = product["components"].get(
            "customer_preferred_export_rule", "Not Found"
        )
        can_grid_charge = not product["components"].get(
            "disallow_charge_from_grid_with_solar_installed", False
        )

        if can_export != "battery_ok" or not can_grid_charge:
            raise ValueError(
                f"Invalid powerwall config - export: {can_export}, "
                f"grid_charge: {can_grid_charge}"
            )

        return {
            "operation_mode": product.get("operation"),
            "backup_percent": product["backup_reserve_percent"],
            "battery_percent": product["percentage_charged"],
            "can_export": can_export,
            "can_grid_charge": can_grid_charge,
        }

    def calculate_trigger_percentages(
        self, decision_point, current_time, sleep_time: int
    ) -> tuple:
        """Calculate trigger percentages for current and next polling cycle."""
        hours_to_end = (
            (int(decision_point.time_end / 100) - current_time.tm_hour)
            + (decision_point.time_end % 100 - current_time.tm_min) / 60
            - current_time.tm_sec / 3600
        )

        trigger_now = round(
            decision_point.pct_thresh
            - (decision_point.pct_gradient_per_hr * hours_to_end),
            2,
        )
        trigger_next = round(
            trigger_now + decision_point.pct_gradient_per_hr * (sleep_time / 3600), 2
        )

        return trigger_now, trigger_next

    def apply_decision_point(
        self, product, data: dict, decision_point, trigger_percentage: float
    ) -> bool:
        """Apply a decision point configuration to the powerwall."""
        status_messages = []
        changes_made = False

        # Update operation mode if needed
        current_op_mode = data.get("operation_mode") or self.cached_op_mode
        if current_op_mode != decision_point.op_mode:
            status = product.set_operation(decision_point.op_mode)
            self.cached_op_mode = decision_point.op_mode
            status_messages.append(f"Mode: {status} {decision_point.op_mode}")
            changes_made = True

        # Calculate desired minimum percentage
        desired_min = decision_point.pct_min
        if decision_point.pct_min_trail_stop:
            # Trailing stop to avoid unnecessary battery drain
            desired_min = data["backup_percent"]
            while (
                data["battery_percent"]
                >= desired_min + decision_point.pct_min_trail_stop
            ):
                desired_min += decision_point.pct_min_trail_stop

        # Update backup reserve if needed
        if data["backup_percent"] != desired_min:
            status = product.set_backup_reserve_percent(int(desired_min))
            status_messages.append(f"Reserve: {status} {desired_min}%")
            changes_made = True

        # Send notification for reserve changes
        if changes_made:
            message = (
                f"At: {data['battery_percent']}%, {decision_point.reason} - "
                f"{' | '.join(status_messages)}"
            )
            self.logger.warning(message)

            if self.send_notifications or decision_point.always_notify:
                self.pushover.send_message(message, title="Powerwall Alert", priority=0)

        return changes_made

    def process_decision_points(
        self, product, data: dict, current_time, sleep_time: int
    ) -> int:
        """Process all decision points and return updated sleep time."""
        decision_points = Constants.POWERWALL_DECISION_POINTS
        current_time_val = current_time.tm_hour * 100 + current_time.tm_min

        for decision_point in decision_points:
            if not (
                decision_point.time_start <= current_time_val < decision_point.time_end
            ):
                continue

            trigger_now, trigger_next = self.calculate_trigger_percentages(
                decision_point, current_time, sleep_time
            )

            future_pct = self.battery_history.extrapolate() or data["battery_percent"]

            self.logger.info(
                f"Evaluating {decision_point.reason}: "
                f"current={data['battery_percent']:.2f}% vs "
                f"trigger={trigger_now:.2f}%, future={future_pct:.2f}% vs "
                f"next_trigger={trigger_next:.2f}%"
            )

            # Check if current condition matches
            if self.evaluate_condition(
                data["battery_percent"], trigger_now, decision_point.iff_higher
            ):
                self.logger.info(f"Matched current condition: {decision_point.reason}")
                self.apply_decision_point(product, data, decision_point, trigger_now)
                return sleep_time

            # Check if future condition will match (fast retry)
            elif self.evaluate_condition(
                future_pct, trigger_next, decision_point.iff_higher
            ):
                self.logger.warning(
                    f"Future condition match: {decision_point.reason} - fast retry"
                )
                return min(sleep_time, 60)

            else:
                self.logger.info(
                    f"In time window but no match: {decision_point.reason}"
                )

        self.logger.warning("No decision point matched - is this expected?")
        return sleep_time

    def run_monitoring_loop(self) -> None:
        """Main monitoring loop."""
        with TeslaClient(self.email, verify=False) as client:
            product = client.battery_list()[0]
            site_name = product["site_name"]
            self.logger.info(f"Connected to site: {site_name}")
            self.pushover.send_message(f"Powerwall monitoring started for: {site_name}", title="Powerwall Alert", priority=0)

            sleep_time = 0

            while True:
                self.loop_count += 1
                time.sleep(sleep_time)

                importlib.reload(Constants)  # hot refresh on config.

                current_time = time.localtime()
                poll_time = Constants.POWERWALL_POLL_TIME

                self.logger.info(f"Loop {self.loop_count}")

                try:
                    data = self.get_powerwall_data(product)

                    # Sanitize battery percentage
                    data["battery_percent"] = self.sanitize_battery_percentage(
                        data["battery_percent"], sleep_time / poll_time
                    )

                    self.logger.info(
                        f"Battery: {data['battery_percent']:.2f}%, "
                        f"Mode: {data['operation_mode']}, "
                        f"Export: {data['can_export']}, "
                        f"Grid charge: {data['can_grid_charge']}"
                    )

                    # Process decision points
                    sleep_time = self.process_decision_points(
                        product, data, current_time, poll_time
                    )
                    self.fail_count = 0

                except Exception as e:
                    self.fail_count += 1
                    self.logger.warning(f"Attempt {self.fail_count} failed: {e}")

                    if self.fail_count > 10:
                        raise RuntimeError(f"Too many consecutive failures: {e}")

                    sleep_time = min(poll_time, 30)  # Quick retry
                    continue


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Tesla Powerwall Management System")
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "-e", "--email", default=Constants.POWERWALL_EMAIL, help="Tesla account email"
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress stdout logging"
    )
    parser.add_argument(
        "--send-notifications",
        action="store_true",
        help="Enable notifications via Pushover",
    )

    args = parser.parse_args()

    logger = get_logger(__name__)
    logger.info("=" * 50)
    logger.info(f"Started: {' '.join(sys.argv)}")

    try:
        manager = PowerwallManager(args.email, args.send_notifications)
        manager.run_monitoring_loop()

    except EnvironmentError as e:
        error_msg = f"Tesla token expired? Run TeslaPy gui.py. Error: {e}"
        logger = get_logger(__name__)
        logger.error(error_msg)
        manager.pushover.send_message("Tesla token expired - run TeslaPy gui.py", title="Powerwall Alert", priority=2)

    except Exception as e:
        import traceback

        tb_str = traceback.format_exc()
        logger = get_logger(__name__)
        logger.error(f"Unexpected error: {e}\nTraceback:\n{tb_str}")
        if "manager" in locals():
            manager.pushover.send_message(f"Powerwall monitoring error: {e}", title="Powerwall Alert", priority=1)

    finally:
        logger = get_logger(__name__)
        logger.error("Exiting after 1-hour delay to prevent respawn churn")
        time.sleep(3600)


if __name__ == "__main__":
    main()
