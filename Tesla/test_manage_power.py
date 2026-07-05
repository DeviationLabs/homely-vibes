#!/usr/bin/env python3
"""Unit tests for Tesla/manage_power.py.

Uses dependency injection (pushover=MagicMock(spec=Pushover)) rather than
`sys.modules[...] = MagicMock()`. The old approach clobbered the real `lib`
namespace globally at collection time and broke unrelated tests (RingSecurity,
RingBeams, lib.file_lock, lib.secure_io) whenever they ran in the same
process. See CLAUDE.md "NEVER use patch()" — inject dependencies through
the production API instead.
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from lib.MyPushover import Pushover
from Tesla.manage_power import BatteryHistory, DecisionPoint, PowerwallManager


class TestBatteryHistory(unittest.TestCase):
    """Test cases for BatteryHistory class."""

    def setUp(self) -> None:
        self.history = BatteryHistory()

    def test_init(self) -> None:
        self.assertEqual(len(self.history.percentages), 0)
        self.assertEqual(self.history.MAX_HISTORY, 5)

    def test_add_percentage(self) -> None:
        self.history.add_percentage(85.5)
        self.assertEqual(len(self.history.percentages), 1)
        self.assertEqual(self.history.percentages[0], 85.5)

        self.history.add_percentage(84.2)
        self.history.add_percentage(83.1)
        self.assertEqual(len(self.history.percentages), 3)
        self.assertEqual(self.history.percentages, [83.1, 84.2, 85.5])

    def test_max_history_limit(self) -> None:
        for i in range(7):
            self.history.add_percentage(80.0 + i)
        self.assertEqual(len(self.history.percentages), 5)
        self.assertEqual(self.history.percentages, [86.0, 85.0, 84.0, 83.0, 82.0])

    def test_get_average_gradient(self) -> None:
        self.assertEqual(self.history.get_average_gradient(), 0.0)

        self.history.add_percentage(85.0)
        self.assertEqual(self.history.get_average_gradient(), 0.0)

        self.history.percentages = [80.0, 85.0, 90.0]  # Most recent first
        gradient = self.history.get_average_gradient()
        expected = ((80.0 - 85.0) + (85.0 - 90.0)) / 2  # (-5 + -5) / 2 = -5
        self.assertEqual(gradient, expected)

        self.history.percentages = [90.0, 85.0, 80.0]
        gradient = self.history.get_average_gradient()
        expected = ((90.0 - 85.0) + (85.0 - 80.0)) / 2  # (5 + 5) / 2 = 5
        self.assertEqual(gradient, expected)

    def test_extrapolate(self) -> None:
        self.assertIsNone(self.history.extrapolate())

        self.history.add_percentage(85.0)
        self.assertEqual(self.history.extrapolate(), 85.0)

        self.history.percentages = [80.0, 85.0, 90.0]
        self.assertEqual(self.history.extrapolate(1.0), round(80.0 + (-5.0 * 1.0), 2))
        self.assertEqual(self.history.extrapolate(0.5), round(80.0 + (-5.0 * 0.5), 2))


class TestPowerwallManager(unittest.TestCase):
    """Test cases for PowerwallManager class."""

    def setUp(self) -> None:
        # DI: fake Pushover so we never touch real config or Amit's phone.
        self.manager = PowerwallManager(
            "test@example.com",
            send_notifications=False,
            pushover=MagicMock(spec=Pushover),
        )

    def test_init(self) -> None:
        self.assertEqual(self.manager.email, "test@example.com")
        self.assertEqual(self.manager.send_notifications, False)
        self.assertIsInstance(self.manager.battery_history, BatteryHistory)
        self.assertEqual(self.manager.loop_count, 0)
        self.assertEqual(self.manager.fail_count, 0)

    def test_evaluate_condition(self) -> None:
        # direction_up=True → drain condition, trigger when actual > threshold
        self.assertTrue(self.manager.evaluate_condition(85.0, 80.0, True))
        self.assertFalse(self.manager.evaluate_condition(75.0, 80.0, True))

        # direction_up=False → charge condition, trigger when actual < threshold
        self.assertTrue(self.manager.evaluate_condition(75.0, 80.0, False))
        self.assertFalse(self.manager.evaluate_condition(85.0, 80.0, False))

        # Equal on either side → no trigger
        self.assertFalse(self.manager.evaluate_condition(80.0, 80.0, True))
        self.assertFalse(self.manager.evaluate_condition(80.0, 80.0, False))

    def test_sanitize_battery_percentage(self) -> None:
        result = self.manager.sanitize_battery_percentage(85.5, 1.0)
        self.assertEqual(result, 85.5)
        self.assertEqual(len(self.manager.battery_history.percentages), 1)

        # Zero with full history → extrapolate
        self.manager.battery_history.percentages = [80.0, 82.0, 84.0, 86.0, 88.0]
        with patch.object(self.manager.battery_history, "extrapolate", return_value=78.5):
            self.assertEqual(self.manager.sanitize_battery_percentage(0.0, 1.0), 78.5)

        # Duplicate with full history → extrapolate
        self.manager.battery_history.percentages = [80.0, 82.0, 84.0, 86.0, 88.0]
        with patch.object(self.manager.battery_history, "extrapolate", return_value=79.0):
            self.assertEqual(self.manager.sanitize_battery_percentage(80.0, 1.0), 79.0)

        # Clamp above 100
        self.manager.battery_history.percentages = [95.0, 96.0, 97.0, 98.0, 99.0]
        with patch.object(self.manager.battery_history, "extrapolate", return_value=105.0):
            self.assertEqual(self.manager.sanitize_battery_percentage(0.0, 1.0), 100.0)

        # Clamp below 0
        self.manager.battery_history.percentages = [5.0, 4.0, 3.0, 2.0, 1.0]
        with patch.object(self.manager.battery_history, "extrapolate", return_value=-5.0):
            self.assertEqual(self.manager.sanitize_battery_percentage(0.0, 1.0), 0.0)

    def test_calculate_trigger_percentages(self) -> None:
        decision_point = DecisionPoint(
            time_start=800,
            time_end=1200,
            pct_thresh=50.0,
            pct_gradient_per_hr=5.0,
            iff_higher=True,
            op_mode="self_consumption",
            pct_min=20.0,
            pct_min_trail_stop=None,
            reason="test rule",
        )

        # 10:30:00
        mock_time = Mock()
        mock_time.tm_hour = 10
        mock_time.tm_min = 30
        mock_time.tm_sec = 0

        sleep_time = 300  # 5 min

        trigger_now, trigger_next = self.manager.calculate_trigger_percentages(
            decision_point, mock_time, sleep_time
        )

        # Hours to end: 1.5. trigger_now = 50 - 5*1.5 = 42.5.
        # trigger_next = 42.5 + 5*(300/3600) ≈ 42.92.
        self.assertEqual(trigger_now, 42.5)
        self.assertAlmostEqual(trigger_next, 42.92, places=2)


if __name__ == "__main__":
    unittest.main()
