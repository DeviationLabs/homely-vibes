"""Pushover notifier shared by all LaunchJobs wrapper scripts.

Each JobSpec declares its own `pushover_token_key`; we look up the matching
token in `cfg.pushover.tokens`. If the token isn't configured we fall back
to `cfg.pushover.default_token` rather than failing — better to send to a
shared app than to silently drop the notification.
"""

import argparse
import sys
from datetime import datetime
from typing import Protocol

from LaunchJobs.jobs.registry import JobSpec, get_job
from lib.MyPushover import Pushover
from lib.config import get_config


class _Sender(Protocol):
    """Minimal interface a Pushover client needs to expose for `notify`.

    Defining a Protocol lets tests inject a fake sender without `patch()`.
    """

    def send_message(self, message: str, title: str | None = ..., priority: int = ...) -> bool: ...


def _resolve_token(job: JobSpec) -> str:
    cfg = get_config()
    return cfg.pushover.tokens.get(job.pushover_token_key, cfg.pushover.default_token)


def _default_sender(job: JobSpec) -> _Sender:
    cfg = get_config()
    return Pushover(cfg.pushover.user, _resolve_token(job))


def notify(
    job_name: str,
    status: str,
    body: str | None = None,
    sender: _Sender | None = None,
) -> bool:
    """Send a Pushover notification about a launchd job's run.

    Args:
        job_name: Short JobSpec name (key into registry).
        status: e.g. "ok", "fail", "skipped".
        body: Optional message body; auto-generated if omitted.
        sender: Injected client (for tests); falls back to a real Pushover.

    Returns:
        True if Pushover accepted the message.
    """
    job = get_job(job_name)
    client = sender if sender is not None else _default_sender(job)
    title = f"[LaunchJobs] {job.name}: {status}"
    message = body or f"Completed at {datetime.now():%Y-%m-%d %H:%M:%S}"
    return client.send_message(message, title=title, priority=-1)


def main(argv: list[str] | None = None) -> int:
    """CLI shim invoked from wrapper scripts: `python -m LaunchJobs.notify ...`."""
    parser = argparse.ArgumentParser(description="Send a LaunchJobs Pushover notification")
    parser.add_argument("job", help="Registered job name")
    parser.add_argument("--status", required=True, help="ok | fail | skipped")
    parser.add_argument("--body", default=None, help="Optional message body")
    args = parser.parse_args(argv)
    ok = notify(args.job, args.status, args.body)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
