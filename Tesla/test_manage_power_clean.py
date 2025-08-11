#!/usr/bin/env python3
"""Unit tests for manage_power_clean.py"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import time
import logging
from dataclasses import dataclass

# Mock the Constants module before importing
import sys
from unittest.mock import MagicMock
sys.modules['Constants'] = MagicMock()
sys.modules['lib'] = MagicMock()
sys.modules['lib.MyPushover'] = MagicMock()
sys.modules['TeslaPy'] = MagicMock()
sys.modules['TeslaPy.teslapy'] = MagicMock()

# Import the classes we're testing
from Tesla.manage_power_clean import BatteryHistory, PowerwallManager, DecisionPoint


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


if __name__ == '__main__':
    unittest.main()