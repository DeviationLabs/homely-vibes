"""Cross-section config invariants.

`_validate_shared_invariants` is exercised directly against a constructed
Config -- `get_config()` is a module-level singleton, so calling it here would
bind the real YAML for the rest of the session.
"""

from __future__ import annotations

import pytest

from lib.config import RingBeamsConfig, RingConfig, _validate_shared_invariants


def _cfg(ring_path: str, beams_path: str):
    class _Stub:
        ring = RingConfig(
            username="u",
            password="p",
            battery_threshold_pct=25,
            token_file=ring_path,
        )
        ring_beams = RingBeamsConfig(
            token_file=beams_path,
            battery_threshold_pct=25,
            sidecar_timeout_seconds=45,
        )

    return _Stub()


def test_matching_ring_token_paths_pass() -> None:
    _validate_shared_invariants(_cfg("config/tokens/ring.json", "config/tokens/ring.json"))


def test_divergent_ring_token_paths_are_rejected() -> None:
    """RingSecurity and RingBeams share one rotating refresh token and lock a
    sentinel derived from this path. Diverge them and each locks a private file,
    mutual exclusion vanishes silently, and the loser hits invalid_grant days
    later. Fail at load instead."""
    with pytest.raises(ValueError, match="same file"):
        _validate_shared_invariants(_cfg("config/tokens/a.json", "config/tokens/b.json"))
