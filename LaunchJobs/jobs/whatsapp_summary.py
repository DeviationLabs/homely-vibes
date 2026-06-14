"""WhatsApp daily summary launchd job.

Invokes the `pi` (@earendil-works/pi-coding-agent) skill
`productivity:whatsapp-summary` non-interactively via a bash wrapper.
The skill itself owns its output (no MD-file post-processing here).
"""

import os
from pathlib import Path

from LaunchJobs.jobs.registry import JobSpec
from lib.config import get_config

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER_SCRIPT = _REPO_ROOT / "LaunchJobs" / "scripts" / "run_whatsapp_summary.sh"


def _build() -> JobSpec:
    cfg = get_config()
    wa = cfg.launch_jobs.whatsapp_summary

    return JobSpec(
        name="whatsapp-summary",
        label="com.deviationlabs.launchjobs.whatsapp-summary",
        program=["/bin/zsh", "-l", str(_WRAPPER_SCRIPT)],
        schedule={"Hour": wa.hour, "Minute": wa.minute},
        stdout_path=Path(os.path.expanduser(wa.stdout_path)),
        stderr_path=Path(os.path.expanduser(wa.stderr_path)),
        pushover_token_key="WhatsAppSummary",
        env={
            "HOME": os.path.expanduser("~"),
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
        description="Daily WhatsApp summary via pi + productivity:whatsapp-summary skill",
        legacy_labels=("com.abutala.whatsapp-summary",),
    )


JOB: JobSpec = _build()
