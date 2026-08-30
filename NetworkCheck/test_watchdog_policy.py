"""Tests for the watchdog's decision policy.

Pure function of (state, now, config), so every branch is reachable without a
network, a clock or a router. This is the module worth over-testing: it is the
one that decides whether the house reboots its own router at 3am.

One clock now covers both faults, so the policy no longer knows or cares which
symptom started it -- that distinction lives in `_detect_fault` and is tested
in test_uplink_watchdog.
"""

from NetworkCheck.conftest import HOUR, NOW, make_cfg
from NetworkCheck.watchdog_policy import should_act
from NetworkCheck.watchdog_state import WatchdogState


def test_healthy_never_acts() -> None:
    assert should_act(WatchdogState(), NOW, make_cfg()).act is False


def test_short_fault_waits() -> None:
    decision = should_act(WatchdogState(down_since=NOW - HOUR), NOW, make_cfg())
    assert decision.act is False
    assert "threshold" in decision.reason


def test_fault_past_threshold_acts() -> None:
    assert should_act(WatchdogState(down_since=NOW - 2 * HOUR), NOW, make_cfg()).act is True


def test_retry_interval_blocks_a_second_action() -> None:
    state = WatchdogState(
        down_since=NOW - 3 * HOUR,
        last_action_ts=NOW - HOUR,
        actions=[{"ts": NOW - HOUR}],
    )
    decision = should_act(state, NOW, make_cfg())
    assert decision.act is False
    assert "retry" in decision.reason


def test_retry_window_reopens() -> None:
    state = WatchdogState(
        down_since=NOW - 5 * HOUR,
        last_action_ts=NOW - 3 * HOUR,
        actions=[{"ts": NOW - 3 * HOUR}],
    )
    assert should_act(state, NOW, make_cfg()).act is True


def test_daily_cap_stops_acting() -> None:
    state = WatchdogState(
        down_since=NOW - 9 * HOUR,
        last_action_ts=NOW - 3 * HOUR,
        actions=[{"ts": NOW - 8 * HOUR}, {"ts": NOW - 3 * HOUR}],
    )
    decision = should_act(state, NOW, make_cfg(max_actions_per_day=2))
    assert decision.act is False
    assert "budget" in decision.reason


def test_actions_older_than_a_day_do_not_count_against_the_cap() -> None:
    state = WatchdogState(
        down_since=NOW - 3 * HOUR,
        last_action_ts=NOW - 30 * HOUR,
        actions=[{"ts": NOW - 30 * HOUR}],
    )
    assert should_act(state, NOW, make_cfg(max_actions_per_day=1)).act is True


def test_zero_cap_means_unlimited() -> None:
    state = WatchdogState(
        down_since=NOW - 30 * HOUR,
        last_action_ts=NOW - 3 * HOUR,
        actions=[{"ts": NOW - i * HOUR} for i in range(1, 12)],
    )
    assert should_act(state, NOW, make_cfg(max_actions_per_day=0)).act is True


def test_the_clock_does_not_care_which_symptom_started_it() -> None:
    """The point of merging: a router that alternates symptoms still trips.

    Two separate clocks each reset on their own, so a Deco whose WAN dies for
    40 min, recovers, then loses its radios for 20 min, recovers, and repeats,
    never accumulated enough on either one. One clock -- reset only by a fully
    healthy cycle -- reaches the threshold.
    """
    state = WatchdogState(down_since=NOW - 2 * HOUR, fault_reason="Wi-Fi down (0/25)")
    assert should_act(state, NOW, make_cfg()).act is True
    state.fault_reason = "Internet down"
    assert should_act(state, NOW, make_cfg()).act is True
