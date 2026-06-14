"""JobSpec dataclass + registry of all homely_vibes-managed launchd jobs."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class JobSpec:
    """Declarative definition of a launchd job.

    A JobSpec is the single source of truth for one scheduled task. The
    launchjobs CLI renders it to a plist, bootstraps it into launchd,
    queries its status, and tails its logs.

    Attributes:
        name: Short key used on the CLI (e.g. "whatsapp-summary").
        label: launchd `Label` (reverse-DNS, must be globally unique).
        program: `ProgramArguments` — argv launchd invokes.
        schedule: `StartCalendarInterval` payload (Hour/Minute/Weekday/...).
        stdout_path: File path launchd routes stdout to.
        stderr_path: File path launchd routes stderr to.
        pushover_token_key: Key into cfg.pushover.tokens — each job has its
            own Pushover app, matching the RachioFlume convention.
        env: EnvironmentVariables to inject. HOME is always needed under launchd.
        description: Free-text shown by `launchjobs list`.
        legacy_labels: Old launchd Labels to bootout-and-remove during install.
            Used when consolidating plists out of other repos.
    """

    name: str
    label: str
    program: list[str]
    schedule: dict[str, int]
    stdout_path: Path
    stderr_path: Path
    pushover_token_key: str
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""
    legacy_labels: tuple[str, ...] = ()


def _load_all_jobs() -> dict[str, JobSpec]:
    """Import each job module and register its spec.

    Adding a new job: create LaunchJobs/jobs/<name>.py exposing a `JOB`
    module-level JobSpec, then add an import here.
    """
    from LaunchJobs.jobs.whatsapp_summary import JOB as WHATSAPP_SUMMARY

    return {WHATSAPP_SUMMARY.name: WHATSAPP_SUMMARY}


JOBS: dict[str, JobSpec] = _load_all_jobs()


def get_job(name: str) -> JobSpec:
    """Lookup a JobSpec by short name. Raises KeyError if unknown."""
    if name not in JOBS:
        known = ", ".join(sorted(JOBS)) or "<none>"
        raise KeyError(f"Unknown job '{name}'. Known: {known}")
    return JOBS[name]


def list_jobs() -> list[JobSpec]:
    """Return all registered JobSpecs."""
    return list(JOBS.values())
