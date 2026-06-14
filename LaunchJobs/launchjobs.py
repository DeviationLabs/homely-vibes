#!/usr/bin/env python3
"""launchjobs — one CLI to manage homely_vibes-owned macOS launchd jobs."""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from LaunchJobs.jobs.registry import JOBS, JobSpec, get_job, list_jobs
from LaunchJobs.plist_template import plist_install_path, write_plist
from lib.logger import get_logger


def _domain() -> str:
    """launchctl domain target for the current GUI user."""
    return f"gui/{os.getuid()}"


def _service_target(job: JobSpec) -> str:
    return f"{_domain()}/{job.label}"


def _run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a command, capturing combined output as text. Never raises on non-zero unless check=True."""
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _is_loaded(label: str) -> bool:
    """Probe launchctl for a label. True if the service is bootstrapped in our domain."""
    proc = _run(["launchctl", "print", f"{_domain()}/{label}"])
    return proc.returncode == 0


def _bootout(label: str) -> None:
    """Best-effort `launchctl bootout` — silently skip if not loaded."""
    _run(["launchctl", "bootout", f"{_domain()}/{label}"])


def _bootstrap(plist_path: Path) -> subprocess.CompletedProcess[str]:
    return _run(["launchctl", "bootstrap", _domain(), str(plist_path)], check=True)


def _kickstart(label: str) -> subprocess.CompletedProcess[str]:
    return _run(["launchctl", "kickstart", "-k", f"{_domain()}/{label}"], check=True)


def _format_schedule(schedule: dict[str, int]) -> str:
    """Render StartCalendarInterval as a human-readable string."""
    return ", ".join(f"{k}={v}" for k, v in schedule.items())


def cmd_list(_args: argparse.Namespace) -> int:
    logger = get_logger(__name__)
    logger.info("Registered jobs:")
    for job in list_jobs():
        loaded = "LOADED" if _is_loaded(job.label) else "not loaded"
        logger.info(f"  {job.name:25s} [{loaded}]  label={job.label}")
        logger.info(f"    schedule: {_format_schedule(job.schedule)}")
        if job.description:
            logger.info(f"    desc:     {job.description}")
    return 0


def _evict_legacy(job: JobSpec) -> None:
    """Bootout + back up and delete any legacy plists this job consolidates."""
    logger = get_logger(__name__)
    for legacy_label in job.legacy_labels:
        if _is_loaded(legacy_label):
            logger.info(f"Booting out legacy service {legacy_label}")
            _bootout(legacy_label)
        legacy_plist = Path.home() / "Library" / "LaunchAgents" / f"{legacy_label}.plist"
        if legacy_plist.exists():
            backup = legacy_plist.with_suffix(
                f".plist.bak.{datetime.now():%Y%m%d_%H%M%S}",
            )
            shutil.move(str(legacy_plist), str(backup))
            logger.info(f"Backed up legacy plist: {legacy_plist} -> {backup}")


def cmd_install(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)
    job = get_job(args.job)
    _evict_legacy(job)

    if _is_loaded(job.label):
        logger.info(f"Service already loaded; booting out before re-install: {job.label}")
        _bootout(job.label)

    plist_path = plist_install_path(job)
    write_plist(job, plist_path)
    logger.info(f"Wrote plist: {plist_path}")

    try:
        _bootstrap(plist_path)
    except subprocess.CalledProcessError as exc:
        logger.error(f"bootstrap failed: rc={exc.returncode} stderr={exc.stderr.strip()}")
        return 1
    logger.info(f"Bootstrapped {job.label}")

    # Confirm and surface next run window.
    if not _is_loaded(job.label):
        logger.error("Service did not load after bootstrap")
        return 1
    logger.info(f"OK. Next run honors schedule: {_format_schedule(job.schedule)}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)
    job = get_job(args.job)
    if _is_loaded(job.label):
        _bootout(job.label)
        logger.info(f"Booted out {job.label}")
    plist_path = plist_install_path(job)
    if plist_path.exists():
        plist_path.unlink()
        logger.info(f"Removed plist: {plist_path}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)
    if args.job:
        job = get_job(args.job)
        proc = _run(["launchctl", "print", _service_target(job)])
        if proc.returncode != 0:
            logger.warning(f"{job.label}: not loaded")
            return 1
        sys.stdout.write(proc.stdout)
        return 0

    # No job specified: summary of all registered jobs.
    for job in list_jobs():
        logger.info(
            f"{job.name} ({job.label}): {'LOADED' if _is_loaded(job.label) else 'not loaded'}"
        )
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)
    job = get_job(args.job)
    path = job.stderr_path if args.err else job.stdout_path
    if not path.exists():
        logger.warning(f"Log file does not exist yet: {path}")
        return 0
    with path.open("r", errors="replace") as fh:
        lines = fh.readlines()
    tail = lines[-args.tail :] if args.tail > 0 else lines
    sys.stdout.write("".join(tail))
    return 0


def cmd_trigger(args: argparse.Namespace) -> int:
    logger = get_logger(__name__)
    job = get_job(args.job)
    if not _is_loaded(job.label):
        logger.error(f"{job.label} not loaded; run `install` first")
        return 1
    try:
        _kickstart(job.label)
    except subprocess.CalledProcessError as exc:
        logger.error(f"kickstart failed: rc={exc.returncode} stderr={exc.stderr.strip()}")
        return 1
    logger.info(f"Kickstarted {job.label}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Execute the wrapper script in-process, bypassing launchd.

    Useful for local testing — surfaces the wrapper's stdout/stderr directly.
    """
    logger = get_logger(__name__)
    job = get_job(args.job)
    logger.info(f"Running wrapper for {job.name}: {' '.join(job.program)}")
    env = os.environ.copy()
    env.update(job.env)
    proc = subprocess.run(job.program, env=env)
    return proc.returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage homely_vibes-owned macOS launchd jobs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Show registered jobs and load state")

    p = sub.add_parser("install", help="Install + bootstrap a job")
    p.add_argument("job", choices=sorted(JOBS))

    p = sub.add_parser("uninstall", help="Bootout and delete a job's plist")
    p.add_argument("job", choices=sorted(JOBS))

    p = sub.add_parser("status", help="Show launchctl status for a job (or all)")
    p.add_argument("job", nargs="?", choices=sorted(JOBS), default=None)

    p = sub.add_parser("logs", help="Tail a job's stdout (or --err for stderr)")
    p.add_argument("job", choices=sorted(JOBS))
    p.add_argument("--err", action="store_true", help="Tail stderr instead of stdout")
    p.add_argument("--tail", type=int, default=100, help="Number of trailing lines")

    p = sub.add_parser("trigger", help="Kickstart a job (force run now)")
    p.add_argument("job", choices=sorted(JOBS))

    p = sub.add_parser("run", help="Run the wrapper script directly (no launchd)")
    p.add_argument("job", choices=sorted(JOBS))

    return parser


_DISPATCH = {
    "list": cmd_list,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "status": cmd_status,
    "logs": cmd_logs,
    "trigger": cmd_trigger,
    "run": cmd_run,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return _DISPATCH[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
