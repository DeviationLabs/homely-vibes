"""
Pytest configuration for homely-vibes test suite.
Adds project root to sys.path to enable imports from any test directory.
"""

import lib  # noqa: F401
import sys
from pathlib import Path

# Add project root to Python path for imports
project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))
