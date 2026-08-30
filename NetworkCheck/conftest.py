"""Shared fixtures for the NetworkCheck suite.

Fakes live here rather than in each test module: three files need the same
notifier and Deco stand-ins, and the repo forbids `patch()`, so the fakes are
the test surface and duplicating them would let them drift apart.
"""

import logging
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from lib.config import UplinkWatchdogConfig
from NetworkCheck.uplink_watchdog import UplinkWatchdog

HOUR = 3600
NOW = 1_700_000_000.0
FAKE_ADMIN_CRED = "fake-local-admin"
MASTER_MAC = "AA:BB:CC:DD:EE:FF"
SLAVE_MAC = "11:22:33:44:55:66"


def make_cfg(**overrides: Any) -> UplinkWatchdogConfig:
    base: dict[str, Any] = dict(
        enabled=True,
        deco_host="http://192.168.x.x",
        deco_username="admin",
        deco_password=FAKE_ADMIN_CRED,
        probe_targets=["1.1.1.1:443"],
        outage_threshold_secs=2 * HOUR,
        retry_interval_secs=2 * HOUR,
        max_actions_per_day=0,
        auth_check_interval_secs=86400,
        min_wireless_clients=0,
        modem_host="",
        modem_username="admin",
        modem_password=FAKE_ADMIN_CRED,
        state_file="uplink_watchdog_state.json",
    )
    base.update(overrides)
    return UplinkWatchdogConfig(**base)


class FakeNotifier:
    """`raises=True` stands in for a Notifier implementation that throws.

    `lib.MyPushover` returns False, but `Notifier` is a Protocol -- the
    watchdog does not get to assume every backend is as well behaved.
    """

    def __init__(self, succeed: bool = True, raises: bool = False) -> None:
        self.sent: list[tuple[str, Optional[str], int]] = []
        self.succeed = succeed
        self.raises = raises

    def send_message(self, message: str, title: Optional[str] = None, priority: int = 0) -> bool:
        if self.raises:
            raise RuntimeError("notifier exploded")
        if self.succeed:
            self.sent.append((message, title, priority))
        return self.succeed


def wifi_clients(wireless: int, wired: int = 2) -> list[dict[str, Any]]:
    """A client_list in the shape the Deco returns, with a known radio count."""
    clients: list[dict[str, Any]] = [
        {"connection_type": "wired", "interface": "main", "ip": f"192.168.x.{i}", "online": True}
        for i in range(wired)
    ]
    clients += [
        {
            "connection_type": "band5" if i % 2 else "band2_4",
            "interface": "main",
            "ip": f"192.168.x.{100 + i}",
            "online": True,
        }
        for i in range(wireless)
    ]
    return clients


class FakeDeco:
    """Stands in for DecoClient. Records reboots instead of performing them."""

    def __init__(
        self,
        error: Optional[Exception] = None,
        wireless: int = 12,
        reboot_error: Optional[Exception] = None,
    ) -> None:
        self.error = error
        # Failure confined to the reboot call: the shape of a router that
        # accepted the command and dropped the connection on its way down.
        self.reboot_error = reboot_error
        self.reboots: list[list[str]] = []
        self.decos: list[dict[str, Any]] = [
            {"role": "master", "mac": MASTER_MAC},
            {"role": "slave", "mac": SLAVE_MAC},
        ]
        # Two wired hosts are always present -- the monitoring host is one of
        # them, which is the whole reason a dead radio plane looks healthy.
        self.clients: list[dict[str, Any]] = wifi_clients(wireless)

    def list_decos(self) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        return self.decos

    def list_clients(self) -> list[dict[str, Any]]:
        if self.error:
            raise self.error
        return self.clients

    def reboot(self, macs: list[str]) -> None:
        if self.error:
            raise self.error
        self.reboots.append(macs)
        if self.reboot_error:
            raise self.reboot_error


class FakeModem:
    """Stands in for ModemClient. Records reboots instead of performing them.

    Exposes only `reboot()` -- the same narrow surface the watchdog depends
    on, so a test can never reach the factory-reset button either.
    """

    def __init__(
        self, error: Optional[Exception] = None, verify_error: Optional[Exception] = None
    ) -> None:
        self.error = error
        # Failure confined to the read-only check: the shape of a firmware that
        # renumbered the reset buttons while the credential still works.
        self.verify_error = verify_error
        self.reboots = 0
        self.verifies = 0

    def verify(self) -> str:
        self.verifies += 1
        if self.verify_error or self.error:
            raise self.verify_error or self.error  # type: ignore[misc]
        return "btn1 present and labelled 'reset the gateway'"

    def reboot(self) -> None:
        if self.error:
            raise self.error
        self.reboots += 1


@pytest.fixture
def logger() -> logging.Logger:
    log = logging.getLogger("networkcheck_tests")
    log.addHandler(logging.NullHandler())
    return log


BuildFn = Callable[..., tuple[UplinkWatchdog, FakeDeco, FakeNotifier]]
ModemBuildFn = Callable[..., tuple[UplinkWatchdog, FakeDeco, FakeModem]]


@pytest.fixture
def build(tmp_path: Path, logger: logging.Logger) -> BuildFn:
    """Factory returning (watchdog, fake deco, fake notifier)."""

    def _build(
        cfg: Optional[UplinkWatchdogConfig] = None,
        internet: bool = False,
        deco: Optional[FakeDeco] = None,
        notifier: Optional[FakeNotifier] = None,
        modem: Optional[FakeModem] = None,
    ) -> tuple[UplinkWatchdog, FakeDeco, FakeNotifier]:
        deco = deco or FakeDeco()
        notifier = notifier or FakeNotifier()
        modem = modem or FakeModem()
        watchdog = UplinkWatchdog(
            cfg or make_cfg(),
            notifier,
            logger,
            str(tmp_path / "state.json"),
            deco_factory=lambda: deco,
            internet_probe=lambda: internet,
            modem_factory=lambda: modem,
        )
        return watchdog, deco, notifier

    return _build
