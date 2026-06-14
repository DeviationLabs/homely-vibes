"""Job registry — one JobSpec per launchd job managed by homely_vibes."""

from LaunchJobs.jobs.registry import JOBS, JobSpec, get_job, list_jobs

__all__ = ["JOBS", "JobSpec", "get_job", "list_jobs"]
