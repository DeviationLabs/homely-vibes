"""
Pytest configuration for homely-vibes test suite.
Adds project root to sys.path to enable imports from any test directory.
"""

import os
import sys
from pathlib import Path

# Git exports GIT_DIR, GIT_INDEX_FILE and friends into every hook it runs, and
# the pre-commit hook runs `make test`, so pytest inherits them. GIT_DIR beats
# both `-C` and `cwd`, so without this any subprocess git call in a test
# retargets the real repo instead of its tmp fixture — `git init`/`git config`
# in a fixture then rewrite the developer's own .git/config (observed: core.bare
# flipped, a stray core.worktree added, user.name/email overwritten). Scrub at
# import time, before any test or fixture runs.
for _var in (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_PREFIX",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
):
    os.environ.pop(_var, None)

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
import lib.file_lock  # noqa: F401, E402
import lib.Mailer  # noqa: F401, E402
import lib.MyPushover  # noqa: F401, E402
import lib.NetHelpers  # noqa: F401, E402
import lib.logger  # noqa: F401, E402
import lib.secure_io  # noqa: F401, E402
