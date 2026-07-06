"""Shared notification abstractions.

`Notifier` is a send-only Protocol satisfied by `lib.MyPushover.Pushover` and by
test fakes. Modules should depend on this Protocol at their DI boundary rather
than importing the concrete `Pushover` class — this keeps tests free of
`patch()` and lets us swap notification backends per-module without touching
monitor code.
"""

from typing import Protocol


class Notifier(Protocol):
    """Send-only notification surface (satisfied by Pushover or test fakes)."""

    def send_message(self, message: str, title: str | None = None, priority: int = 0) -> bool: ...
