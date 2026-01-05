#!/usr/bin/env python3
"""Unit tests for manage_power_clean.py"""

import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

# Mock external modules before importing our code
mock_pushover_class = MagicMock()
mock_pushover_module = MagicMock()
mock_pushover_module.Pushover = mock_pushover_class

sys.modules["lib"] = MagicMock()
sys.modules["lib.MyPushover"] = mock_pushover_module
sys.modules["lib.logger"] = MagicMock()
sys.modules["TeslaPy"] = MagicMock()
sys.modules["TeslaPy.teslapy"] = MagicMock()
sys.modules["lib.TeslaPy"] = MagicMock()
sys.modules["lib.TeslaPy.teslapy"] = MagicMock()

from Tesla.manage_power import BatteryHistory, PowerwallManager, DecisionPoint


class TestBatteryHistory(unittest.TestCase):
    """Test cases for BatteryHistory class."""

    def setUp(self):
        """Set up test fixtures."""
        self.history = BatteryHistory()

    def test_init(self):
        """Test BatteryHistory initialization."""
        self.assertEqual(len(self.history.percentages), 0)
        self.assertEqual(self.history.MAX_HISTORY, 5)

    def test_add_percentage(self):
        """Test adding percentages to history."""
        self.history.add_percentage(85.5)
        self.assertEqual(len(self.history.percentages), 1)
        self.assertEqual(self.history.percentages[0], 85.5)

        # Add more percentages
        self.history.add_percentage(84.2)
        self.history.add_percentage(83.1)
        self.assertEqual(len(self.history.percentages), 3)
        self.assertEqual(self.history.percentages, [83.1, 84.2, 85.5])

    def test_max_history_limit(self):
        """Test that history doesn't exceed MAX_HISTORY."""
        # Add more than MAX_HISTORY items
        for i in range(7):
            self.history.add_percentage(80.0 + i)

        self.assertEqual(len(self.history.percentages), 5)
        # Should contain the 5 most recent values
        expected = [86.0, 85.0, 84.0, 83.0, 82.0]
        self.assertEqual(self.history.percentages, expected)

    def test_get_average_gradient(self):
        """Test average gradient calculation."""
        # Test empty history
        self.assertEqual(self.history.get_average_gradient(), 0.0)

        # Test single value
        self.history.add_percentage(85.0)
        self.assertEqual(self.history.get_average_gradient(), 0.0)

        # Test declining battery (negative gradient)
        self.history.percentages = [80.0, 85.0, 90.0]  # Most recent first
        gradient = self.history.get_average_gradient()
        expected = ((80.0 - 85.0) + (85.0 - 90.0)) / 2  # (-5 + -5) / 2 = -5
        self.assertEqual(gradient, expected)

        # Test charging battery (positive gradient)
        self.history.percentages = [90.0, 85.0, 80.0]  # Most recent first
        gradient = self.history.get_average_gradient()
        expected = ((90.0 - 85.0) + (85.0 - 80.0)) / 2  # (5 + 5) / 2 = 5
        self.assertEqual(gradient, expected)

    def test_extrapolate(self):
        """Test battery percentage extrapolation."""
        # Test empty history
        self.assertIsNone(self.history.extrapolate())

        # Test single value (no gradient available)
        self.history.add_percentage(85.0)
        self.assertEqual(self.history.extrapolate(), 85.0)

        # Test declining battery
        self.history.percentages = [80.0, 85.0, 90.0]
        extrapolated = self.history.extrapolate(1.0)  # 1 time unit
        expected = round(80.0 + (-5.0 * 1.0), 2)  # 80 - 5 = 75
        self.assertEqual(extrapolated, expected)

        # Test with different time sampling
        extrapolated = self.history.extrapolate(0.5)  # 0.5 time units
        expected = round(80.0 + (-5.0 * 0.5), 2)  # 80 - 2.5 = 77.5
        self.assertEqual(extrapolated, expected)


class TestPowerwallManager(unittest.TestCase):
    """Test cases for PowerwallManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = PowerwallManager("test@example.com", send_notifications=False)

    def test_init(self):
        """Test PowerwallManager initialization."""
        self.assertEqual(self.manager.email, "test@example.com")
        self.assertEqual(self.manager.send_notifications, False)
        self.assertIsInstance(self.manager.battery_history, BatteryHistory)
        self.assertEqual(self.manager.loop_count, 0)
        self.assertEqual(self.manager.fail_count, 0)

    def test_evaluate_condition(self):
        """Test condition evaluation for triggering actions."""
        # Test direction_up = True (drain condition)
        self.assertTrue(self.manager.evaluate_condition(85.0, 80.0, True))  # 85 > 80
        self.assertFalse(self.manager.evaluate_condition(75.0, 80.0, True))  # 75 < 80

        # Test direction_up = False (charge condition)
        self.assertTrue(self.manager.evaluate_condition(75.0, 80.0, False))  # 75 < 80
        self.assertFalse(self.manager.evaluate_condition(85.0, 80.0, False))  # 85 > 80

        # Test edge cases
        self.assertFalse(self.manager.evaluate_condition(80.0, 80.0, True))  # Equal, up
        self.assertFalse(self.manager.evaluate_condition(80.0, 80.0, False))  # Equal, down

    def test_sanitize_battery_percentage(self):
        """Test battery percentage sanitization."""
        # Test normal percentage
        result = self.manager.sanitize_battery_percentage(85.5, 1.0)
        self.assertEqual(result, 85.5)
        self.assertEqual(len(self.manager.battery_history.percentages), 1)

        # Test zero percentage with history - should use extrapolation
        self.manager.battery_history.percentages = [
            80.0,
            82.0,
            84.0,
            86.0,
            88.0,
        ]  # Full history
        with patch.object(self.manager.battery_history, "extrapolate", return_value=78.5):
            result = self.manager.sanitize_battery_percentage(0.0, 1.0)
            self.assertEqual(result, 78.5)

        # Test duplicate percentage with full history - should use extrapolation
        self.manager.battery_history.percentages = [
            80.0,
            82.0,
            84.0,
            86.0,
            88.0,
        ]
        with patch.object(self.manager.battery_history, "extrapolate", return_value=79.0):
            result = self.manager.sanitize_battery_percentage(80.0, 1.0)  # Duplicate
            self.assertEqual(result, 79.0)

        # Test percentage > 100 gets clamped
        self.manager.battery_history.percentages = [
            95.0,
            96.0,
            97.0,
            98.0,
            99.0,
        ]
        with patch.object(self.manager.battery_history, "extrapolate", return_value=105.0):
            result = self.manager.sanitize_battery_percentage(0.0, 1.0)
            self.assertEqual(result, 100.0)  # Should be clamped to 100

        # Test percentage < 0 gets clamped
        self.manager.battery_history.percentages = [5.0, 4.0, 3.0, 2.0, 1.0]
        with patch.object(self.manager.battery_history, "extrapolate", return_value=-5.0):
            result = self.manager.sanitize_battery_percentage(0.0, 1.0)
            self.assertEqual(result, 0.0)  # Should be clamped to 0

    def test_calculate_trigger_percentages(self):
        """Test trigger percentage calculations."""
        # Create a test decision point
        decision_point = DecisionPoint(
            time_start=800,  # 08:00
            time_end=1200,  # 12:00
            pct_thresh=50.0,
            pct_gradient_per_hr=5.0,
            iff_higher=True,
            op_mode="self_consumption",
            pct_min=20.0,
            pct_min_trail_stop=None,
            reason="test rule",
        )

        # Mock current time: 10:30:00 (10.5 hours, 30 minutes, 0 seconds)
        mock_time = Mock()
        mock_time.tm_hour = 10
        mock_time.tm_min = 30
        mock_time.tm_sec = 0

        sleep_time = 300  # 5 minutes = 300 seconds

        trigger_now, trigger_next = self.manager.calculate_trigger_percentages(
            decision_point, mock_time, sleep_time
        )

        # Calculate expected values
        # Hours to end: (12 - 10) + (0 - 30)/60 - 0/3600 = 2 - 0.5 = 1.5 hours
        # trigger_now = 50.0 - (5.0 * 1.5) = 50.0 - 7.5 = 42.5
        # trigger_next = 42.5 + (5.0 * (300/3600)) = 42.5 + 0.42 = 42.92

        self.assertEqual(trigger_now, 42.5)
        self.assertAlmostEqual(trigger_next, 42.92, places=2)


if __name__ == "__main__":
    unittest.main()
