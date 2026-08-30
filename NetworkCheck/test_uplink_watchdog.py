"""Tests for the watchdog's orchestration.

Policy lives in test_watchdog_policy, persistence in test_watchdog_state. What
is left here is the wiring: what one tick sees, what reaches Pushover and when,
and what the reboot actually targets.
"""

import json
from pathlib import Path
from typing import Any

from NetworkCheck.conftest import (
    HOUR,
    MASTER_MAC,
    NOW,
    SLAVE_MAC,
    BuildFn,
    FakeDeco,
    FakeModem,
    FakeNotifier,
    make_cfg,
    wifi_clients,
)
from NetworkCheck.deco_client import DecoAPIError, DecoAuthError
from NetworkCheck.modem_client import ModemAPIError, ModemAuthError
from NetworkCheck.uplink_watchdog import brief

WIFI_ON = dict(min_wireless_clients=6)
MODEM_HOST = "http://10.0.0.x"


class TestRebootTargets:
    """Every node, not just the master."""

    def test_reboot_all_targets_every_node(self, build: BuildFn) -> None:
        watchdog, deco, _ = build()
        macs = watchdog.reboot_all()
        assert set(macs) == {MASTER_MAC, SLAVE_MAC}
        assert deco.reboots == [macs]

    def test_reboot_is_one_call_carrying_the_whole_mesh(self, build: BuildFn) -> None:
        """The router takes a mac_list, so this must not be a call per node."""
        watchdog, deco, _ = build()
        watchdog.reboot_all()
        assert len(deco.reboots) == 1
        assert len(deco.reboots[0]) == 2

    def test_a_sustained_fault_reboots_every_node(self, build: BuildFn) -> None:
        watchdog, deco, _ = build()
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert set(deco.reboots[0]) == {MASTER_MAC, SLAVE_MAC}

    def test_empty_mesh_is_an_error_not_a_silent_no_op(self, build: BuildFn) -> None:
        deco = FakeDeco()
        deco.decos = []
        watchdog, _, _ = build(deco=deco)
        try:
            watchdog.reboot_all()
            raise AssertionError("expected DecoAPIError")
        except DecoAPIError as err:
            assert "nothing to reboot" in str(err)

    def test_nodes_without_a_mac_are_skipped(self, build: BuildFn) -> None:
        deco = FakeDeco()
        deco.decos = [{"role": "master", "mac": MASTER_MAC}, {"role": "slave"}]
        watchdog, _, _ = build(deco=deco)
        assert watchdog.reboot_all() == [MASTER_MAC]


class TestOneClock:
    """Both symptoms feed a single clock that only a healthy cycle resets."""

    def test_internet_down_starts_the_clock(self, build: BuildFn) -> None:
        watchdog, deco, _ = build(internet=False)
        watchdog.check_once(now=NOW)
        assert watchdog.state.down_since == NOW
        assert watchdog.state.fault_reason == "Internet down"
        assert deco.reboots == []

    def test_wifi_down_starts_the_same_clock(self, build: BuildFn) -> None:
        watchdog, deco, _ = build(cfg=make_cfg(**WIFI_ON), internet=True, deco=FakeDeco(wireless=0))
        watchdog.check_once(now=NOW)
        assert watchdog.state.down_since == NOW
        assert "Wi-Fi down (0/6" in str(watchdog.state.fault_reason)
        assert deco.reboots == []

    def test_a_healthy_cycle_clears_the_clock(self, build: BuildFn) -> None:
        watchdog, _, _ = build(internet=True)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.state.fault_reason = "Internet down"
        watchdog.check_once(now=NOW)
        # Read back from disk: the cleared clock has to survive the tick, and
        # a reload is the only view mypy will not narrow away.
        reloaded, _, _ = build(internet=True)
        assert reloaded.state.down_since is None
        assert reloaded.state.fault_reason is None

    def test_the_clock_survives_a_symptom_change(self, build: BuildFn) -> None:
        """The whole reason for merging: alternating symptoms still accumulate.

        Two independent clocks each reset on their own, so this router would
        never have been rebooted despite being sick the entire time.
        """
        watchdog, deco, _ = build(cfg=make_cfg(**WIFI_ON), internet=False)
        watchdog.check_once(now=NOW)  # internet down
        assert watchdog.state.down_since == NOW

        # Uplink returns but the radios are dead -- still a fault, same clock.
        watchdog.internet_probe = lambda: True
        deco.clients = wifi_clients(wireless=0)
        watchdog.check_once(now=NOW + HOUR)
        assert watchdog.state.down_since == NOW
        assert "Wi-Fi down" in str(watchdog.state.fault_reason)

        # Two hours after the *first* symptom, it acts.
        watchdog.check_once(now=NOW + 2 * HOUR)
        assert len(deco.reboots) == 1

    def test_wifi_is_not_checked_while_the_uplink_is_down(self, build: BuildFn) -> None:
        """A census during an outage cannot be told from one against a mesh
        that is already rebooting -- and could not be delivered anyway.
        """
        deco = FakeDeco(error=DecoAPIError("should not be called"))
        watchdog, _, _ = build(cfg=make_cfg(**WIFI_ON), internet=False, deco=deco)
        watchdog.check_once(now=NOW)
        assert watchdog.state.fault_reason == "Internet down"

    def test_dry_run_decides_but_does_not_act(self, build: BuildFn) -> None:
        watchdog, deco, _ = build()
        watchdog.state.down_since = NOW - 3 * HOUR
        assert watchdog.check_once(now=NOW, dry_run=True).act is True
        assert deco.reboots == []
        assert watchdog.state.last_action_ts is None


class TestCensusFailsClosed:
    """An unreadable router counts as a router serving nobody."""

    def test_a_failed_census_counts_as_zero(self, build: BuildFn) -> None:
        watchdog, _, _ = build(
            cfg=make_cfg(**WIFI_ON), internet=True, deco=FakeDeco(error=DecoAPIError("boom"))
        )
        watchdog.check_once(now=NOW)
        assert watchdog.state.down_since == NOW
        assert "Wi-Fi down (0/6" in str(watchdog.state.fault_reason)

    def test_a_failed_census_is_silent(self, build: BuildFn) -> None:
        """No alert on a transient failure -- the log has it, and a persistent
        one reaches the reboot (with its own P1) on its own.
        """
        watchdog, _, notifier = build(
            cfg=make_cfg(**WIFI_ON), internet=True, deco=FakeDeco(error=DecoAPIError("boom"))
        )
        watchdog.check_once(now=NOW)
        assert notifier.sent == []
        assert watchdog.state.pending == []

    def test_a_raw_exception_also_counts_as_zero(self, build: BuildFn) -> None:
        watchdog, _, _ = build(
            cfg=make_cfg(**WIFI_ON), internet=True, deco=FakeDeco(error=RuntimeError("raw"))
        )
        watchdog.check_once(now=NOW)
        assert watchdog.state.down_since == NOW

    def test_a_persistently_failing_census_eventually_reboots(self, build: BuildFn) -> None:
        """The point of failing closed: it cannot go silently blind forever."""
        deco = FakeDeco(error=DecoAPIError("boom"))
        watchdog, _, _ = build(cfg=make_cfg(**WIFI_ON), internet=True, deco=deco)
        watchdog.check_once(now=NOW)
        deco.error = None
        deco.clients = wifi_clients(wireless=0)
        watchdog.check_once(now=NOW + 2 * HOUR)
        assert len(deco.reboots) == 1

    def test_a_failed_census_does_not_stamp_the_auth_clock(self, build: BuildFn) -> None:
        """Only a *successful* login may stand in for the credential check."""
        watchdog, _, _ = build(
            cfg=make_cfg(**WIFI_ON), internet=True, deco=FakeDeco(error=DecoAPIError("boom"))
        )
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_auth_check_ts is None

    def test_the_check_is_skipped_entirely_when_disabled(self, build: BuildFn) -> None:
        deco = FakeDeco(error=DecoAPIError("should not be called"), wireless=0)
        watchdog, _, _ = build(internet=True, deco=deco)
        assert watchdog.check_once(now=NOW).reason == "mesh healthy"
        assert watchdog.state.down_since is None


class TestFailureHandling:
    def test_auth_failure_queues_p0_and_records_no_action(self, build: BuildFn) -> None:
        watchdog, _, _ = build(deco=FakeDeco(error=DecoAuthError("bad password")))
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_action_ts is None
        assert [p["priority"] for p in watchdog.state.pending] == [0]

    def test_api_failure_before_the_reboot_records_nothing(self, build: BuildFn) -> None:
        """Enumeration failed, so no reboot was ever issued."""
        watchdog, _, _ = build(deco=FakeDeco(error=DecoAPIError("boom")))
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert watchdog.state.pending[-1]["priority"] == 1
        assert watchdog.state.last_action_ts is None

    def test_a_reboot_that_does_not_confirm_still_counts_as_an_action(self, build: BuildFn) -> None:
        """The router drops the connection on its way down.

        Treating that as "nothing happened" leaves retry_interval_secs
        unarmed, so the next tick reboots again -- a loop that never lets the
        mesh finish booting, and one no alert escapes to report.
        """
        deco = FakeDeco(reboot_error=DecoAPIError("connection reset by peer"))
        watchdog, _, _ = build(deco=deco)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_action_ts == NOW
        assert any("not confirmed" in p["message"] for p in watchdog.state.pending)

    def test_the_retry_interval_holds_after_an_unconfirmed_reboot(self, build: BuildFn) -> None:
        deco = FakeDeco(reboot_error=DecoAPIError("connection reset by peer"))
        watchdog, _, _ = build(deco=deco)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        watchdog.check_once(now=NOW + 600)
        assert len(deco.reboots) == 1

    def test_a_raw_exception_from_the_reboot_cannot_kill_the_tick(self, build: BuildFn) -> None:
        """The worst place in the module for an escape: it happens *after* the
        reboot was issued, so it would lose the note and leave the next tick
        reading a state file that records an action nobody can explain.
        """
        deco = FakeDeco(reboot_error=RuntimeError("raw crypto blowup"))
        watchdog, _, _ = build(deco=deco)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_action_ts == NOW
        assert any("not confirmed" in p["message"] for p in watchdog.state.pending)

    def test_a_notifier_that_raises_degrades_to_the_queue(self, build: BuildFn) -> None:
        """`Notifier` is a Protocol; not every backend returns False politely.

        A raise between `record_action()` and `_save()` would leave the action
        in memory, never on disk, and skip the reboot entirely.
        """
        deco = FakeDeco(wireless=0)
        watchdog, _, _ = build(
            cfg=make_cfg(**WIFI_ON),
            internet=True,
            deco=deco,
            notifier=FakeNotifier(raises=True),
        )
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_action_ts == NOW
        assert any("rebooting" in p["message"] for p in watchdog.state.pending)
        assert len(deco.reboots) == 1


class TestModemStage:
    """The upstream gateway is the extra swing, never the swing itself."""

    def test_an_internet_fault_reboots_the_modem_first(self, build: BuildFn) -> None:
        modem = FakeModem()
        watchdog, deco, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), modem=modem)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert modem.reboots == 1
        assert len(deco.reboots) == 1

    def test_a_wifi_fault_leaves_the_modem_alone(self, build: BuildFn) -> None:
        """The uplink is working by definition; rebooting it helps nobody."""
        modem = FakeModem()
        watchdog, deco, _ = build(
            cfg=make_cfg(modem_host=MODEM_HOST, **WIFI_ON),
            internet=True,
            deco=FakeDeco(wireless=0),
            modem=modem,
        )
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert modem.reboots == 0
        assert len(deco.reboots) == 1

    def test_an_empty_modem_host_disables_the_stage(self, build: BuildFn) -> None:
        modem = FakeModem()
        watchdog, deco, _ = build(modem=modem)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert modem.reboots == 0
        assert len(deco.reboots) == 1

    def test_a_modem_failure_never_blocks_the_mesh_reboot(self, build: BuildFn) -> None:
        """The gateway sits past the Deco, so it may be unreachable during the
        exact fault we want it for. The proven lever must still be pulled.
        """
        modem = FakeModem(error=ModemAPIError("no route to host"))
        watchdog, deco, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), modem=modem)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert len(deco.reboots) == 1
        assert watchdog.state.last_action_ts == NOW

    def test_a_raw_modem_exception_also_does_not_block(self, build: BuildFn) -> None:
        modem = FakeModem(error=RuntimeError("raw"))
        watchdog, deco, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), modem=modem)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert len(deco.reboots) == 1

    def test_dry_run_touches_neither(self, build: BuildFn) -> None:
        modem = FakeModem()
        watchdog, deco, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), modem=modem)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW, dry_run=True)
        assert modem.reboots == 0
        assert deco.reboots == []

    def test_a_deco_auth_failure_still_lets_the_modem_reboot(self, build: BuildFn) -> None:
        """Two independent levers: losing the Deco credential must not also
        forfeit the modem swing.
        """
        modem = FakeModem()
        watchdog, _, _ = build(
            cfg=make_cfg(modem_host=MODEM_HOST),
            deco=FakeDeco(error=DecoAuthError("evicted")),
            modem=modem,
        )
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert modem.reboots == 1


class TestNotifications:
    def test_notifications_queue_during_an_outage(self, build: BuildFn) -> None:
        watchdog, _, notifier = build()
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert notifier.sent == []
        assert len(watchdog.state.pending) == 1

    def test_queue_flushes_on_recovery(self, build: BuildFn) -> None:
        watchdog, _, notifier = build()
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)

        watchdog.internet_probe = lambda: True
        watchdog.check_once(now=NOW + 300)

        assert watchdog.state.pending == []
        # Queue drains in order: the action alert, then the recovery notice.
        assert len(notifier.sent) == 2
        assert notifier.sent[1][2] == -1

    def test_the_queue_also_flushes_during_a_wifi_fault(self, build: BuildFn) -> None:
        """The uplink is up, so queued alerts should not wait on a full
        recovery that may never come.
        """
        watchdog, deco, notifier = build(cfg=make_cfg(**WIFI_ON))
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)  # outage: queues the reboot alert

        watchdog.internet_probe = lambda: True
        deco.clients = wifi_clients(wireless=0)
        watchdog.check_once(now=NOW + 600)

        assert any("rebooting" in m for m, _, _ in notifier.sent)

    def test_failed_send_keeps_the_queue(self, build: BuildFn) -> None:
        watchdog, _, _ = build(notifier=FakeNotifier(succeed=False))
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        watchdog.internet_probe = lambda: True
        watchdog.check_once(now=NOW + 300)
        assert len(watchdog.state.pending) == 2

    def test_repeated_identical_alerts_are_deduplicated(self, build: BuildFn) -> None:
        """A persistent outage ticks every 10 min; the queue must not grow."""
        watchdog, _, _ = build(deco=FakeDeco(error=DecoAuthError("evicted")))
        watchdog.state.down_since = NOW - 3 * HOUR
        for tick in range(6):
            watchdog.check_once(now=NOW + tick * 600)
        assert len(watchdog.state.pending) == 1

    def test_a_notifier_that_raises_while_flushing_keeps_the_queue(self, build: BuildFn) -> None:
        watchdog, _, _ = build(notifier=FakeNotifier(raises=True))
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        watchdog.internet_probe = lambda: True
        watchdog.check_once(now=NOW + 300)
        assert len(watchdog.state.pending) == 2


class TestDeliveryAcrossAReboot:
    """The alert must survive the network the watchdog is about to take away."""

    def test_state_is_on_disk_before_the_reboot_is_issued(
        self, build: BuildFn, tmp_path: Path
    ) -> None:
        class RecordingDeco(FakeDeco):
            """Snapshots the state file at the instant the reboot is issued."""

            def __init__(self, state_path: Path) -> None:
                super().__init__()
                self.state_path = state_path
                self.state_at_reboot: dict[str, Any] = {}

            def reboot(self, macs: list[str]) -> None:
                self.state_at_reboot = json.loads(self.state_path.read_text())
                super().reboot(macs)

        deco = RecordingDeco(tmp_path / "state.json")
        watchdog, _, _ = build(deco=deco)
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)

        # A crash mid-reboot must not lose either fact.
        assert deco.state_at_reboot["last_action_ts"] == NOW
        assert any("rebooting 2 deco(s)" in p["message"] for p in deco.state_at_reboot["pending"])

    def test_the_reboot_alert_lands_once_the_network_returns(self, build: BuildFn) -> None:
        watchdog, _, notifier = build()
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        assert notifier.sent == []

        watchdog.internet_probe = lambda: True
        watchdog.check_once(now=NOW + 600)

        assert any("rebooting 2 deco(s)" in m for m, _, _ in notifier.sent)
        assert watchdog.state.pending == []

    def test_the_recovery_message_names_the_fault_and_the_reboot(self, build: BuildFn) -> None:
        watchdog, _, notifier = build()
        watchdog.state.down_since = NOW - 3 * HOUR
        watchdog.check_once(now=NOW)
        watchdog.internet_probe = lambda: True
        watchdog.check_once(now=NOW + 600)

        recovery = [m for m, _, priority in notifier.sent if priority == -1]
        assert len(recovery) == 1
        assert "Internet down" in recovery[0]
        assert "10 min after the watchdog rebooted the mesh" in recovery[0]

    def test_a_recovery_with_no_action_says_nothing_about_a_reboot(self, build: BuildFn) -> None:
        watchdog, _, notifier = build()
        watchdog.state.down_since = NOW - HOUR
        watchdog.state.fault_reason = "Internet down"
        watchdog.internet_probe = lambda: True
        watchdog.check_once(now=NOW)
        recovery = [m for m, _, priority in notifier.sent if priority == -1]
        assert len(recovery) == 1
        assert "rebooted" not in recovery[0]


class TestAlertText:
    """The first production failure pushed a dict repr to a phone."""

    def test_pool_noise_is_stripped(self) -> None:
        err = DecoAPIError(
            "Deco client_list request failed: "
            "HTTPConnectionPool(host='192.168.1.1', port=80): Read timed out."
        )
        assert brief(err) == "Deco client_list request failed: Read timed out."

    def test_long_messages_are_shortened(self) -> None:
        assert brief(RuntimeError("word " * 200)).endswith("...")
        assert len(brief(RuntimeError("word " * 200))) <= 140

    def test_an_unrecognised_shape_passes_through_intact(self) -> None:
        """Best-effort cosmetics: worst case it is wordier, never wrong."""
        assert brief(RuntimeError("something else entirely")) == "something else entirely"

    def test_the_deco_client_no_longer_emits_a_dict_repr(self, build: BuildFn) -> None:
        watchdog, _, notifier = build(
            internet=True, deco=FakeDeco(error=DecoAuthError("Invalid Deco admin password"))
        )
        watchdog.check_once(now=NOW)
        message = notifier.sent[0][0]
        assert "{" not in message and "}" not in message


class TestScheduledAuthCheck:
    """The credential is otherwise exercised only at the moment of emergency."""

    def test_auth_is_verified_on_a_healthy_cycle(self, build: BuildFn) -> None:
        watchdog, deco, _ = build(internet=True)
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_auth_check_ts == NOW
        assert deco.reboots == []

    def test_success_is_silent(self, build: BuildFn) -> None:
        watchdog, _, notifier = build(internet=True)
        watchdog.check_once(now=NOW)
        assert notifier.sent == []

    def test_failure_alerts_immediately_rather_than_queueing(self, build: BuildFn) -> None:
        """Inline, not queued -- the uplink is up, which is the whole point."""
        watchdog, _, notifier = build(internet=True, deco=FakeDeco(error=DecoAuthError("evicted")))
        watchdog.check_once(now=NOW)
        assert watchdog.state.pending == []
        message, _, priority = notifier.sent[0]
        assert "auth check FAILED" in message
        assert priority == 0

    def test_persistent_failure_alerts_once_per_interval_not_per_tick(self, build: BuildFn) -> None:
        watchdog, _, notifier = build(internet=True, deco=FakeDeco(error=DecoAuthError("evicted")))
        for tick in range(6):
            watchdog.check_once(now=NOW + tick * 600)
        assert len(notifier.sent) == 1

    def test_check_repeats_after_the_interval(self, build: BuildFn) -> None:
        watchdog, _, notifier = build(internet=True, deco=FakeDeco(error=DecoAuthError("evicted")))
        watchdog.check_once(now=NOW)
        watchdog.check_once(now=NOW + 86400)
        assert len(notifier.sent) == 2

    def test_no_auth_check_while_the_uplink_is_down(self, build: BuildFn) -> None:
        """Pointless and unreportable: the alert could not be delivered."""
        watchdog, _, _ = build(internet=False)
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_auth_check_ts is None

    def test_zero_interval_disables_the_check(self, build: BuildFn) -> None:
        watchdog, _, notifier = build(
            cfg=make_cfg(auth_check_interval_secs=0),
            internet=True,
            deco=FakeDeco(error=DecoAuthError("evicted")),
        )
        watchdog.check_once(now=NOW)
        assert notifier.sent == []
        assert watchdog.state.last_auth_check_ts is None

    def test_a_good_census_stands_in_for_it(self, build: BuildFn) -> None:
        """Both are the same authenticated call; don't log in twice a tick."""
        watchdog, _, notifier = build(
            cfg=make_cfg(**WIFI_ON), internet=True, deco=FakeDeco(wireless=12)
        )
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_auth_check_ts is not None
        assert notifier.sent == []

    def test_clock_survives_a_restart(self, build: BuildFn) -> None:
        """The cron case: consecutive processes must not both check."""
        first, _, _ = build(internet=True)
        first.check_once(now=NOW)
        second, _, notifier = build(internet=True, deco=FakeDeco(error=DecoAuthError("evicted")))
        second.check_once(now=NOW + 600)
        assert notifier.sent == []

    def test_an_unexpected_exception_cannot_kill_the_tick(self, build: BuildFn) -> None:
        watchdog, _, notifier = build(internet=True, deco=FakeDeco(error=RuntimeError("raw")))
        assert watchdog.check_once(now=NOW).reason == "mesh healthy"
        assert len(notifier.sent) == 1
        assert watchdog.state.last_auth_check_ts == NOW

    def test_a_failed_alert_send_falls_back_to_the_queue(self, build: BuildFn) -> None:
        watchdog, _, _ = build(
            internet=True,
            deco=FakeDeco(error=DecoAuthError("evicted")),
            notifier=FakeNotifier(succeed=False),
        )
        watchdog.check_once(now=NOW)
        assert "auth check FAILED" in watchdog.state.pending[0]["message"]


class TestDailyGatewayCheck:
    """The modem stage may go months between real exercises.

    Two of its failure modes -- a rotated password and a firmware that
    renumbered the reset buttons -- are silent until the outage it exists for.
    """

    def test_it_runs_on_a_healthy_cycle(self, build: BuildFn) -> None:
        modem = FakeModem()
        watchdog, _, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem)
        watchdog.check_once(now=NOW)
        assert modem.verifies == 1
        assert watchdog.state.last_modem_check_ts == NOW

    def test_success_is_silent(self, build: BuildFn) -> None:
        watchdog, _, notifier = build(cfg=make_cfg(modem_host=MODEM_HOST), internet=True)
        watchdog.check_once(now=NOW)
        assert notifier.sent == []

    def test_it_never_reboots_anything(self, build: BuildFn) -> None:
        modem = FakeModem()
        watchdog, deco, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem)
        watchdog.check_once(now=NOW)
        assert modem.reboots == 0
        assert deco.reboots == []

    def test_a_relabelled_button_alerts_p0(self, build: BuildFn) -> None:
        """The guard firing during the daily check is the whole point: it
        surfaces a firmware renumbering on a good day, not mid-outage.
        """
        modem = FakeModem(verify_error=ModemAPIError("btn1 is now labelled 'wifi'; refusing"))
        watchdog, _, notifier = build(
            cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem
        )
        watchdog.check_once(now=NOW)
        message, _, priority = notifier.sent[0]
        assert priority == 0
        assert "Gateway check FAILED" in message
        assert "btn1" in message

    def test_a_bad_credential_alerts_p0(self, build: BuildFn) -> None:
        modem = FakeModem(verify_error=ModemAuthError("Gateway login did not set a cookie"))
        watchdog, _, notifier = build(
            cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem
        )
        watchdog.check_once(now=NOW)
        assert notifier.sent[0][2] == 0

    def test_persistent_failure_alerts_once_per_interval(self, build: BuildFn) -> None:
        modem = FakeModem(verify_error=ModemAPIError("boom"))
        watchdog, _, notifier = build(
            cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem
        )
        for tick in range(6):
            watchdog.check_once(now=NOW + tick * 600)
        assert len(notifier.sent) == 1

    def test_it_repeats_after_the_interval(self, build: BuildFn) -> None:
        modem = FakeModem(verify_error=ModemAPIError("boom"))
        watchdog, _, notifier = build(
            cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem
        )
        watchdog.check_once(now=NOW)
        watchdog.check_once(now=NOW + 86400)
        assert len(notifier.sent) == 2

    def test_it_uses_its_own_clock_not_the_deco_one(self, build: BuildFn) -> None:
        """Sharing `last_auth_check_ts` would mean it never ran at all -- a
        successful census stamps that on every single tick.
        """
        modem = FakeModem()
        watchdog, _, _ = build(
            cfg=make_cfg(modem_host=MODEM_HOST, **WIFI_ON),
            internet=True,
            deco=FakeDeco(wireless=12),
            modem=modem,
        )
        watchdog.check_once(now=NOW)
        assert watchdog.state.last_auth_check_ts == NOW  # stamped by the census
        assert modem.verifies == 1  # ...and the gateway check still ran

    def test_no_check_while_the_uplink_is_down(self, build: BuildFn) -> None:
        """Unreportable, and the fault path is about to reboot it anyway."""
        modem = FakeModem()
        watchdog, _, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), internet=False, modem=modem)
        watchdog.check_once(now=NOW)
        assert modem.verifies == 0

    def test_an_empty_modem_host_disables_it(self, build: BuildFn) -> None:
        modem = FakeModem()
        watchdog, _, _ = build(internet=True, modem=modem)
        watchdog.check_once(now=NOW)
        assert modem.verifies == 0

    def test_zero_interval_disables_it(self, build: BuildFn) -> None:
        modem = FakeModem(verify_error=ModemAPIError("boom"))
        watchdog, _, notifier = build(
            cfg=make_cfg(modem_host=MODEM_HOST, auth_check_interval_secs=0),
            internet=True,
            modem=modem,
        )
        watchdog.check_once(now=NOW)
        assert modem.verifies == 0
        assert notifier.sent == []

    def test_the_clock_survives_a_restart(self, build: BuildFn) -> None:
        """The cron case: consecutive processes must not both check."""
        first, _, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), internet=True)
        first.check_once(now=NOW)
        modem = FakeModem()
        second, _, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem)
        second.check_once(now=NOW + 600)
        assert modem.verifies == 0

    def test_a_failure_cannot_kill_the_tick(self, build: BuildFn) -> None:
        modem = FakeModem(verify_error=RuntimeError("raw"))
        watchdog, _, _ = build(cfg=make_cfg(modem_host=MODEM_HOST), internet=True, modem=modem)
        assert watchdog.check_once(now=NOW).reason == "mesh healthy"


class TestReadOnlyCommands:
    """`probe` and `clients` must never touch the reboot path."""

    def test_probe_lists_every_node(self, build: BuildFn) -> None:
        watchdog, deco, _ = build()
        lines = watchdog.probe_deco()
        assert "2 deco(s) found" in lines[0]
        assert any(MASTER_MAC in line for line in lines)
        assert deco.reboots == []

    def test_census_reports_the_split_and_the_verdict(self, build: BuildFn) -> None:
        watchdog, deco, _ = build(cfg=make_cfg(**WIFI_ON), deco=FakeDeco(wireless=3))
        lines = watchdog.wifi_census()
        assert "3 on the radios, 2 wired" in lines[0]
        assert "fault" in lines[1]
        assert deco.reboots == []

    def test_census_never_prints_client_names(self, build: BuildFn) -> None:
        """Household device names in a cron log buy nothing the decision uses."""
        deco = FakeDeco()
        deco.clients = [
            {"connection_type": "band5", "interface": "main", "ip": "1.2.3.4", "name": "SECRET"}
        ]
        watchdog, _, _ = build(cfg=make_cfg(**WIFI_ON), deco=deco)
        assert not any("SECRET" in line for line in watchdog.wifi_census())
