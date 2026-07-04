"""Unit tests for the two shared helpers in alert_rules.

- `compact_zone_label` — display-name normalization used by both the
  reporter and the hose Pushover header.
- `send_zone_outcome_pushover` — the shared zone-end notification format
  that alert_engine and hose_timer_processor both delegate to.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from RachioFlume.alert_rules import (
    compact_zone_label,
    send_zone_outcome_pushover,
)


class TestCompactZoneLabel:
    """Header/display normalization is shared across the controller and hose paths."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Z1 FS", "Z1 FS"),  # controller name — pass through
            ("Z13 FS - Upper Deck Planters", "Z13 FS"),  # hose valve — drop tail
            ("Simple", "Simple"),  # no dash — pass through
            ("  Z2 FS  - Front Yard  ", "Z2 FS"),  # whitespace stripped
            ("Z9 - A - B", "Z9"),  # only first " - " is the split point
            ("Z-1 FS", "Z-1 FS"),  # dash without surrounding spaces — no split
        ],
    )
    def test_variants(self, raw: str, expected: str) -> None:
        assert compact_zone_label(raw) == expected


class TestSendZoneOutcomePushover:
    """The shared helper the controller and hose paths delegate to."""

    def _kwargs(self, **overrides: object) -> dict:
        """Base kwargs matching a typical controller zone-end fire."""
        base: dict = dict(
            pushover=MagicMock(),
            logger=logging.getLogger("test"),
            log_label="'Z1 FS'",
            header="'Z1 FS'",
            runtime_min=30.0,
            avg_gpm=5.0,
            total_gal=150.0,
            baseline=4.0,
            threshold=4.5,
            min_runtime_minutes=5,
        )
        base.update(overrides)
        return base

    def test_short_run_is_silenced(self) -> None:
        kw = self._kwargs(runtime_min=3.0)
        send_zone_outcome_pushover(**kw)
        kw["pushover"].send_message.assert_not_called()

    def test_report_below_threshold(self) -> None:
        # avg_gpm 5.0 < threshold 6.0 → Zone Report at P-1
        kw = self._kwargs(threshold=6.0)
        send_zone_outcome_pushover(**kw)
        kw["pushover"].send_message.assert_called_once()
        _, call_kwargs = kw["pushover"].send_message.call_args
        assert call_kwargs["title"] == "RachioFlume: Zone Report"
        assert call_kwargs["priority"] == -1

    def test_anomaly_above_threshold(self) -> None:
        # avg_gpm 5.0 > threshold 4.5 with baseline > 0 → Zone Anomaly at P2
        kw = self._kwargs()
        send_zone_outcome_pushover(**kw)
        kw["pushover"].send_message.assert_called_once()
        args, call_kwargs = kw["pushover"].send_message.call_args
        assert call_kwargs["title"] == "RachioFlume: Zone Anomaly"
        assert call_kwargs["priority"] == 2
        # Deviation line appended for anomaly path
        assert "Deviation:" in args[0]

    def test_no_baseline_hides_threshold_annotation(self) -> None:
        kw = self._kwargs(baseline=0.0, threshold=0.5)
        send_zone_outcome_pushover(**kw)
        args, _ = kw["pushover"].send_message.call_args
        # No "(thresh X.XX)" suffix when baseline is unknown
        assert "thresh" not in args[0]

    def test_extra_lines_appended(self) -> None:
        # Hose path passes a sensor status line via extra_lines
        kw = self._kwargs(extra_lines=["Flow sensor: detected"])
        send_zone_outcome_pushover(**kw)
        args, _ = kw["pushover"].send_message.call_args
        assert "Flow sensor: detected" in args[0]

    def test_empty_extra_line_filtered(self) -> None:
        # Falsy strings in extra_lines shouldn't produce trailing blank lines
        kw = self._kwargs(extra_lines=[""])
        send_zone_outcome_pushover(**kw)
        args, _ = kw["pushover"].send_message.call_args
        assert not args[0].endswith("\n")
