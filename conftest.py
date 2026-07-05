"""
Pytest configuration for homely-vibes test suite.
Adds project root to sys.path to enable imports from any test directory.
"""

import sys
from pathlib import Path

# Path insert MUST precede the lib imports below — otherwise, when pytest is
# invoked with only child dirs on argv (e.g. `pytest Tesla RachioFlume`), the
# repo root is not yet on sys.path and `import lib` fails.
project_root = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_root))

# Pre-import lib submodules that production code imports at module load time.
# Tesla tests replace sys.modules["lib"] with a MagicMock; any lib.* submodule
# not already cached then fails to import with "'lib' is not a package".
# Importing them here caches the real modules before any test clobbers "lib".
import lib  # noqa: F401, E402
import lib.config  # noqa: F401, E402
import lib.secure_io  # noqa: F401, E402
