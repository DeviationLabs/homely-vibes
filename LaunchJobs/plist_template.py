"""Build launchd plist payloads from a JobSpec.

We use the stdlib `plistlib` rather than templated XML so that Apple's
parser-compatible writer handles escaping, types, and the doctype header.
"""

import plistlib
from pathlib import Path

from LaunchJobs.jobs.registry import JobSpec


def build_plist_dict(job: JobSpec) -> dict[str, object]:
    """Render a JobSpec to the dict launchd expects.

    Keys mirror the plist XML keys exactly so launchctl can consume the
    result after `plistlib.dumps()`.
    """
    payload: dict[str, object] = {
        "Label": job.label,
        "ProgramArguments": list(job.program),
        "StartCalendarInterval": dict(job.schedule),
        "StandardOutPath": str(job.stdout_path),
        "StandardErrorPath": str(job.stderr_path),
        "RunAtLoad": False,
    }
    if job.env:
        payload["EnvironmentVariables"] = dict(job.env)
    return payload


def write_plist(job: JobSpec, target: Path) -> None:
    """Render `job` to `target` (overwriting if it exists)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_plist_dict(job)
    with target.open("wb") as fh:
        plistlib.dump(payload, fh, fmt=plistlib.FMT_XML, sort_keys=False)


def plist_install_path(job: JobSpec) -> Path:
    """Where launchctl expects the user-level plist file to live."""
    return Path.home() / "Library" / "LaunchAgents" / f"{job.label}.plist"
