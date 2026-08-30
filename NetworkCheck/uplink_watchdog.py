#!/usr/bin/env python3
"""Deco watchdog -- a deadman's switch for the home network.

Two symptoms, one fault, one lever.

**WAN wedge.** The Deco periodically wedges its WAN/routing plane (stale WAN
DHCP lease, NAT table exhaustion, DNS-proxy death) while its switch/AP datapath
keeps working. Symptom: LAN is up, the gateway pings, nothing routes past it.

**Radio plane death.** The mirror image, and the one nothing else notices: the
uplink is perfectly healthy -- the monitoring host is wired -- while the mesh
has stopped serving Wi-Fi. Every phone, camera and sensor in the house is off
the air and the uplink probe still reports green.

Both are the same sick router and both are fixed the same way, so they share
one clock and one lever. The whole policy is a sentence: **if the mesh has
looked broken for two hours, reboot every unit; then not again for two hours.**

Because the switch plane survives both faults, the Deco's own local admin API
is still reachable during them -- so the lever is a software reboot, not a
power cut. That fails safe: if the reboot call does not land, nothing is worse
than it already was.

Layout (one concern per module):
    probes.py          -- the only code that touches the real network
    watchdog_state.py  -- what survives between cron ticks
    watchdog_policy.py -- when to act; the whole risk surface, pure and testable
    common.py          -- notifier + invocation banner shared across NetworkCheck

Deployment: cron runs `check` every few minutes (run-once per tick -- fresh
state load each run, free crash recovery, matches the repo cron convention).
"""

import argparse
import json
import logging
import os
import re
import textwrap
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional, Protocol

from lib.config import UplinkWatchdogConfig, get_config
from lib.logger import get_logger
from lib.notifications import Notifier
from NetworkCheck.common import log_invocation, network_notifier
from NetworkCheck.deco_client import (
    DecoAPIError,
    DecoAuthError,
    DecoClient,
    count_wireless_clients,
)
from NetworkCheck.modem_client import ModemClient
from NetworkCheck.probes import probe_internet
from NetworkCheck.watchdog_policy import ActionDecision, should_act
from NetworkCheck.watchdog_state import load_state, save_state

ALERT_TITLE = "Uplink Watchdog"
HEALTHY = "mesh healthy"

# urllib3 prefixes its errors with the pool it failed on. True but useless on a
# phone screen -- the host and port are config, not news.
_POOL_NOISE = re.compile(r"HTTPS?ConnectionPool\([^)]*\):\s*")


def brief(err: Exception, limit: int = 140) -> str:
    """Render an exception for a notification; the log keeps the full chain.

    Best-effort cosmetics, not parsing: if a future exception shape slips past
    the pattern the alert is merely wordier, never wrong. This exists because
    the first production failure of the client census pushed
    ``Deco request to {'form': 'client_list'} failed: HTTPConnectionPool(...)``
    to a phone -- accurate, and unreadable.
    """
    return textwrap.shorten(_POOL_NOISE.sub("", str(err)).strip(), width=limit, placeholder="...")


@dataclass
class Fault:
    """What this cycle saw wrong with the mesh.

    ``deliverable`` says the uplink is up, so an alert can be sent right now --
    which on the Wi-Fi path is also the moment we are about to take it away.
    """

    reason: str
    deliverable: bool


class DecoControl(Protocol):
    """The slice of `DecoClient` the watchdog needs.

    Depending on a Protocol rather than the concrete client keeps tests free of
    `patch()` and lets a fake stand in without inheriting anything -- the same
    boundary `lib.notifications.Notifier` draws for Pushover.
    """

    def list_decos(self) -> list[dict[str, Any]]: ...

    def list_clients(self) -> list[dict[str, Any]]: ...

    def reboot(self, macs: list[str]) -> None: ...


class ModemControl(Protocol):
    """The slice of `ModemClient` the watchdog needs -- exactly one verb.

    Narrow by design: the same admin endpoint also performs a factory wipe, so
    the boundary the watchdog depends on offers no way to ask for anything but
    a reboot.
    """

    def verify(self) -> str: ...

    def reboot(self) -> None: ...


class UplinkWatchdog:
    """Runs one detection/action cycle and persists what it learned."""

    def __init__(
        self,
        cfg: UplinkWatchdogConfig,
        notifier: Notifier,
        logger: logging.Logger,
        state_file: str,
        deco_factory: Optional[Callable[[], DecoControl]] = None,
        internet_probe: Optional[Callable[[], bool]] = None,
        modem_factory: Optional[Callable[[], ModemControl]] = None,
    ) -> None:
        self.cfg = cfg
        self.notifier = notifier
        self.logger = logger
        self.state_file = state_file
        self.deco_factory = deco_factory or (
            lambda: DecoClient(cfg.deco_host, cfg.deco_username, cfg.deco_password)
        )
        self.modem_factory = modem_factory or (
            lambda: ModemClient(cfg.modem_host, cfg.modem_username, cfg.modem_password)
        )
        self.internet_probe = internet_probe or (lambda: probe_internet(list(cfg.probe_targets)))
        self.state = load_state(state_file, logger)

    def check_once(self, now: Optional[float] = None, dry_run: bool = False) -> ActionDecision:
        """One cron tick: probe, decide, maybe act, persist."""
        now = time.time() if now is None else now
        fault = self._detect_fault(now)

        if fault is None:
            self._handle_recovery(now)
            self._maybe_verify_auth(now)
            self._maybe_verify_modem(now)
            self._save()
            return ActionDecision(False, HEALTHY)

        if fault.deliverable:
            # The uplink is up even though the mesh is faulty, so anything
            # queued during an earlier outage goes out now rather than waiting
            # on a full recovery that may never come.
            self._flush_pending()

        if self.state.down_since is None:
            self.logger.warning("Fault detected (%s) -- starting the clock", fault.reason)
            self.state.down_since = now
        self.state.fault_reason = fault.reason

        decision = should_act(self.state, now, self.cfg)
        self.logger.info("Decision: act=%s (%s)", decision.act, decision.reason)

        if decision.act and not dry_run:
            self._execute(now, fault)
        elif decision.act:
            self.logger.info("Dry run -- would have rebooted the mesh")

        self._save()
        return decision

    # ------------------------------------------------------------------ #
    # Detection                                                           #
    # ------------------------------------------------------------------ #

    def _detect_fault(self, now: float) -> Optional[Fault]:
        """What is wrong with the mesh right now, if anything.

        Order matters. The uplink is checked first and short-circuits, because
        a client census taken while the internet is down cannot be told apart
        from one taken against a mesh that is already rebooting -- and the
        alert could not be delivered anyway.

        There is deliberately no LAN/gateway probe. It used to gate the WAN
        path, but `gateway_ip` was the Deco's own address, so it amounted to
        pinging the Deco immediately before logging into it. `_execute` already
        fails safe when the Deco is unreachable: the mesh listing raises before
        any action is recorded, so nothing reboots and the failure is reported.
        """
        if not self.internet_probe():
            return Fault("Internet down", deliverable=False)

        floor = self.cfg.min_wireless_clients
        if not floor:
            return None
        wireless = self._census(now)
        if wireless >= floor:
            return None
        return Fault(f"Wi-Fi down ({wireless}/{floor} clients on the radios)", deliverable=True)

    def _census(self, now: float) -> int:
        """Count clients on the radios. An unreadable router counts as zero.

        Failing closed is the deliberate choice. The alternative -- treating
        "I could not ask" as "everything is fine" -- lets a permanently broken
        census disable this half of the watchdog silently and forever, which is
        the one outcome with no recovery path. A router that will not answer
        its own local admin API is, in any case, a plausible reboot candidate.

        No alert here: a transient timeout is not news, and if the condition
        persists the clock runs and the reboot (with its own P1) follows. A
        credential failure still cannot cause a reboot -- `_execute` lists the
        mesh first and raises there.
        """
        try:
            clients = self.deco_factory().list_clients()
        except Exception as err:
            # Deliberately broad: DecoClient wraps requests errors, but the
            # crypto and key-parsing paths can still raise raw, and this runs
            # before _save().
            self.logger.error("Wireless client census failed; counting as 0: %s", err)
            return 0

        # A successful census proves the credential works, so it stands in for
        # the daily auth check and saves a second login on the same tick.
        # The caller's clock, not wall time: every other timestamp in this
        # module is stamped against `now` so a tick stays deterministic.
        self.state.last_auth_check_ts = now
        return count_wireless_clients(clients)

    # ------------------------------------------------------------------ #
    # Deco actions                                                        #
    # ------------------------------------------------------------------ #

    def _mesh_macs(self, deco: DecoControl) -> list[str]:
        """Every unit in the mesh. Empty is an error, not an empty reboot."""
        macs = [str(d["mac"]) for d in deco.list_decos() if d.get("mac")]
        if not macs:
            raise DecoAPIError("No Deco units found; nothing to reboot")
        return macs

    def probe_deco(self) -> list[str]:
        """Read-only credential smoke test: log in and describe the mesh.

        The only command that exercises the full RSA/AES handshake without
        rebooting anything, which makes it the right thing to run first on a
        new host -- it catches a wrong password, a cron PATH problem or a
        session evicted by an owner login before an outage does.
        """
        decos = self.deco_factory().list_decos()
        lines = [
            f"Authenticated to {self.cfg.deco_host}; {len(decos)} deco(s) found. "
            f"A reboot would target all of them:"
        ]
        for deco in decos:
            lines.append(f"  {deco.get('role', '?'):<7} {deco.get('mac', '?')}")
        return lines

    def wifi_census(self) -> list[str]:
        """Read-only client census -- what the watchdog sees right now.

        This is the tool for choosing `min_wireless_clients`: run it across a
        day, including overnight when phones sleep and the count bottoms out,
        then set the floor well under the observed minimum.

        Client *names* are deliberately not printed. They are the household's
        device names, this output lands in a cron log, and the connection type
        is the only field the decision actually uses.
        """
        clients = self.deco_factory().list_clients()
        wireless = count_wireless_clients(clients)
        floor = self.cfg.min_wireless_clients
        verdict = "fault" if floor and wireless < floor else "healthy"
        lines = [
            f"{len(clients)} client(s) on {self.cfg.deco_host}: "
            f"{wireless} on the radios, {len(clients) - wireless} wired.",
            f"Floor: min_wireless_clients={floor} -- {verdict}"
            f"{'' if floor else ' (Wi-Fi check DISABLED)'}.",
        ]
        for client in sorted(clients, key=lambda c: str(c.get("connection_type", ""))):
            lines.append(
                f"  {str(client.get('connection_type', '?')):<8}"
                f"{str(client.get('interface', '?')):<7}{client.get('ip', '?')}"
            )
        return lines

    def reboot_all(self) -> list[str]:
        """Reboot every unit in the mesh.

        All of them, not just the master: a wedged mesh is not reliably a
        master-only fault, and the satellites re-establish backhaul faster from
        a cold start than they do against a master that just restarted under
        them. The router takes the whole mac_list in one call.
        """
        deco = self.deco_factory()
        macs = self._mesh_macs(deco)
        self.logger.info("Rebooting %d deco(s): %s", len(macs), ", ".join(macs))
        deco.reboot(macs)
        return macs

    def _reboot_modem(self, fault: Fault) -> None:
        """Restart the upstream gateway, best-effort, before the mesh goes down.

        Only on the internet-down fault. On a radio fault the uplink is by
        definition working, so power-cycling a healthy modem would take down a
        good connection for nothing.

        Never fatal, and deliberately so. The gateway sits one hop *past* the
        Deco, so reaching it depends on the very routing plane that a WAN wedge
        breaks -- it may well be unreachable at exactly the moment we want it.
        The Deco reboot is the proven lever and must follow regardless; this is
        the extra swing, not the swing.
        """
        if fault.deliverable or not self.cfg.modem_host:
            return
        try:
            self.modem_factory().reboot()
        except Exception as err:
            # Broad on purpose: this stage is additive, and nothing it can do
            # justifies skipping the Deco reboot below.
            self.logger.error("Gateway reboot failed (continuing to the mesh): %s", err)

    def _execute(self, now: float, fault: Fault) -> None:
        """Reboot the mesh, recording the attempt before it becomes irreversible.

        The ordering is the whole point. Enumerate first, so an auth failure is
        reported with nothing yet on the books. Then record the action, emit
        the alert and persist the state -- and only then make the call that
        takes the network away.

        Recording an *attempt* rather than a success is deliberate:

        * The router drops our connection as it goes down, so the reboot POST
          routinely fails after the router has already accepted it. Counting
          that as "no action taken" leaves `retry_interval_secs` unarmed, and
          the next tick reboots again -- a loop that stops the mesh ever
          finishing a boot, and that no alert escapes to report.
        * On the Wi-Fi path we are about to cut our own uplink on purpose, so
          the alert has to leave (or be durably queued) while it still can.
        """
        self._reboot_modem(fault)

        deco = self.deco_factory()
        try:
            macs = self._mesh_macs(deco)
        except DecoAuthError as err:
            self.logger.error("Deco auth failed: %s", err)
            self._notify(now, f"Deco admin login failed: {brief(err)}", 0, inline=fault.deliverable)
            return
        except DecoAPIError as err:
            self.logger.error("Could not enumerate the mesh: %s", err)
            self._notify(
                now, f"Cannot reach the Deco to reboot: {brief(err)}", 1, inline=fault.deliverable
            )
            return

        self.state.record_action(now)
        self._notify(
            now, f"{fault.reason}; rebooting {len(macs)} deco(s)", 1, inline=fault.deliverable
        )
        self._save()

        self.logger.info("Rebooting %d deco(s): %s", len(macs), ", ".join(macs))
        try:
            deco.reboot(macs)
        except Exception as err:
            # Deliberately broad, same reasoning as the census. An escape here
            # is the worst case in the module -- it happens *after* the reboot
            # was issued, so it would kill the tick, lose this note, and leave
            # the next tick reading a state file that records an action nobody
            # can explain.
            #
            # Queued, not inline: if the reboot did land there is no uplink
            # left to send on. The action stays on the books either way.
            self.logger.error("Reboot call did not confirm: %s", err)
            self._queue(now, f"Reboot issued but not confirmed: {brief(err)}", 1)

    # ------------------------------------------------------------------ #
    # Recovery, auth, notification plumbing                               #
    # ------------------------------------------------------------------ #

    def _handle_recovery(self, now: float) -> None:
        if self.state.down_since is not None:
            mins = int((now - self.state.down_since) / 60)
            was = self.state.fault_reason or "fault"
            self.logger.info("Mesh healthy again after %d min (%s)", mins, was)
            self._queue(now, f"Recovered after {mins} min ({was}){self._reboot_note(now)}", -1)
        self.state.down_since = None
        self.state.fault_reason = None
        self._flush_pending()

    def _reboot_note(self, now: float) -> str:
        """Tie a recovery back to the reboot that (probably) caused it.

        Both alerts arrive on the same tick once the uplink returns; without
        this the reader has to correlate timestamps to learn whether the
        watchdog fixed the fault or merely watched it end.
        """
        acted = self.state.last_action_ts
        if acted is None or self.state.down_since is None or acted < self.state.down_since:
            return ""
        return f", {int((now - acted) / 60)} min after the watchdog rebooted the mesh"

    def _maybe_verify_auth(self, now: float) -> None:
        """Exercise the credential while a failure can still be reported.

        Only matters when the Wi-Fi check is off. With it on, every healthy
        cycle already logs in for the census and stamps the same clock, so this
        never fires -- which is correct, not redundant.

        Login otherwise happens only inside `_execute()` -- at the moment of
        the emergency, never before -- and a failure there is queued behind the
        very outage it was meant to fix, so it surfaces only once the outage
        has resolved some other way. A healthy cycle is the only time we can
        both authenticate and deliver the alert.

        This matters here specifically because the watchdog authenticates as
        the owner account, and an owner login from the Deco phone app evicts
        other sessions at any time.
        """
        interval = self.cfg.auth_check_interval_secs
        if not interval:
            return
        last = self.state.last_auth_check_ts
        if last is not None and now - last < interval:
            return

        # Stamp before attempting, so a persistent failure alerts once per
        # interval rather than on every tick.
        self.state.last_auth_check_ts = now
        try:
            decos = self.deco_factory().list_decos()
        except Exception as err:
            # Deliberately broad. This is a diagnostic and must never be able
            # to kill the tick that runs it -- and because it runs before
            # _save(), an escape would lose the state update too and then fail
            # identically on every following tick.
            self.logger.error("Scheduled auth check failed: %s", err)
            self._notify(
                now,
                f"Deco auth check FAILED; the watchdog cannot reboot the mesh: {brief(err)}",
                0,
                inline=True,
            )
            return
        self.logger.info("Auth check OK (%d deco(s) visible)", len(decos))

    def _maybe_verify_modem(self, now: float) -> None:
        """Exercise the gateway credential and the button guard on a good day.

        The same argument as the Deco auth check, and it bites harder here.
        The modem stage fires only on a sustained internet outage, so it may go
        months between exercises, and two of its failure modes are silent until
        that exact moment: a rotated admin password, and a firmware update that
        renumbered the reset buttons. Checking daily means both surface while
        the uplink is healthy -- which is also the only time the alert can be
        delivered.

        `ModemClient.verify()` runs the identical path as `reboot()` minus the
        POST, so this cannot drift from what it is checking.

        Its own clock, deliberately. Sharing `last_auth_check_ts` would mean it
        never ran: a successful client census stamps that every tick.
        """
        interval = self.cfg.auth_check_interval_secs
        if not interval or not self.cfg.modem_host:
            return
        last = self.state.last_modem_check_ts
        if last is not None and now - last < interval:
            return

        # Stamp before attempting, so a persistent failure reports once per
        # interval rather than on every tick.
        self.state.last_modem_check_ts = now
        try:
            detail = self.modem_factory().verify()
        except Exception as err:
            # Broad for the same reason as every other diagnostic here: it must
            # never kill the tick, and it runs before _save().
            self.logger.error("Gateway check failed: %s", err)
            self._notify(
                now,
                f"Gateway check FAILED; the watchdog cannot reboot the modem: {brief(err)}",
                0,
                inline=True,
            )
            return
        self.logger.info("Gateway check OK (%s)", detail)

    def _notify(self, now: float, message: str, priority: int, *, inline: bool) -> None:
        """Deliver now if the uplink is up, otherwise defer to the flush.

        `inline` is only ever true on a cycle where the internet probed
        healthy. If Pushover itself is down the alert falls back to the queue
        rather than being dropped -- late beats never, and `_flush_pending`
        retries it on the next healthy cycle.
        """
        if inline and self._send_inline(message, priority):
            return
        if inline:
            self.logger.warning("Inline send failed; queued for the next healthy cycle")
        self._queue(now, message, priority)

    def _send_inline(self, message: str, priority: int) -> bool:
        """Attempt one immediate send. Never raises.

        `Notifier` is a Protocol, so the implementation is not ours to trust.
        `lib.MyPushover` returns False rather than raising, but a raise from
        some other backend would escape `_execute` between `record_action()`
        and `_save()` -- the action would live in memory, never reach disk, and
        the reboot would never be issued. That is precisely the ordering this
        module exists to guarantee, so the failure degrades to the queue.
        """
        try:
            return self.notifier.send_message(message, title=ALERT_TITLE, priority=priority)
        except Exception as err:
            self.logger.error("Notifier raised on inline send: %s", err)
            return False

    def _queue(self, now: float, message: str, priority: int) -> None:
        """Stash a notification; it goes out once we have internet again.

        Attempting to send during an outage would just time out. Identical
        messages are deduplicated: a condition that persists across ticks would
        otherwise queue dozens of copies and dump them all at once on recovery.
        """
        if any(p["message"] == message for p in self.state.pending):
            self.logger.debug("Notification already queued, not duplicating: %s", message)
            return
        self.state.pending.append(
            {"ts": now, "message": message, "title": ALERT_TITLE, "priority": priority}
        )
        self.logger.info("Queued notification (P%d): %s", priority, message)

    def _flush_pending(self) -> None:
        """Send queued notifications; keep any that fail for the next tick."""
        unsent = []
        for item in self.state.pending:
            stamp = time.strftime("%H:%M", time.localtime(item["ts"]))
            sent = self._send_inline_item(item, stamp)
            if not sent:
                unsent.append(item)
        if self.state.pending:
            self.logger.info(
                "Flushed %d/%d queued notifications",
                len(self.state.pending) - len(unsent),
                len(self.state.pending),
            )
        self.state.pending = unsent

    def _send_inline_item(self, item: dict[str, Any], stamp: str) -> bool:
        try:
            return self.notifier.send_message(
                f"[{stamp}] {item['message']}",
                title=item["title"],
                priority=item["priority"],
            )
        except Exception as err:
            self.logger.error("Notifier raised while flushing: %s", err)
            return False

    def _save(self) -> None:
        save_state(self.state_file, self.state, self.logger)


def _build(logger: logging.Logger) -> UplinkWatchdog:
    cfg = get_config()
    wd_cfg = cfg.network_check.uplink_watchdog
    state_file = os.path.join(cfg.paths.logging_dir, wd_cfg.state_file)
    return UplinkWatchdog(wd_cfg, network_notifier(), logger, state_file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deco WAN + Wi-Fi watchdog")
    parser.add_argument(
        "command",
        choices=["check", "status", "probe", "clients", "reboot-all", "reboot-modem"],
    )
    parser.add_argument("--dry-run", action="store_true", help="Decide and log, never act")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logger = get_logger(__name__)
    if args.debug:
        logger.setLevel(logging.DEBUG)
    log_invocation(logger)

    watchdog = _build(logger)

    if args.command == "status":
        print(json.dumps(asdict(watchdog.state), indent=2))
        return

    if args.command == "probe":
        for line in watchdog.probe_deco():
            print(line)
        return

    if args.command == "clients":
        for line in watchdog.wifi_census():
            print(line)
        return

    if args.command == "reboot-all":
        macs = watchdog.reboot_all()
        print(f"Reboot issued for {len(macs)} deco(s); the mesh will be down for ~2-3 minutes")
        return

    if args.command == "reboot-modem":
        if not watchdog.cfg.modem_host:
            print("No modem_host configured; nothing to reboot")
            return
        watchdog.modem_factory().reboot()
        print(f"Reboot issued to {watchdog.cfg.modem_host}; expect ~4 minutes of no uplink")
        return

    if not watchdog.cfg.enabled and not args.dry_run:
        logger.info("Watchdog disabled in config; nothing to do")
        return

    decision = watchdog.check_once(dry_run=args.dry_run)
    print(f"act={decision.act} reason={decision.reason}")


if __name__ == "__main__":
    main()
