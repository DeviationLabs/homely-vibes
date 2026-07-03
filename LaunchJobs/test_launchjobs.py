"""Tests for the LaunchJobs module: registry, plist render, notifier."""

import plistlib
from pathlib import Path

import pytest

from LaunchJobs import notify as notify_mod
from LaunchJobs.jobs.registry import JOBS, JobSpec, get_job, list_jobs
from LaunchJobs.plist_template import build_plist_dict, plist_install_path, write_plist


def test_registry_exposes_whatsapp_summary() -> None:
    assert "whatsapp-summary" in JOBS
    job = get_job("whatsapp-summary")
    assert isinstance(job, JobSpec)
    assert job.label == "com.deviationlabs.launchjobs.whatsapp-summary"
    assert job.pushover_token_key == "WhatsAppSummary"
    assert "com.abutala.whatsapp-summary" in job.legacy_labels


def test_list_jobs_returns_all_registered() -> None:
    assert {j.name for j in list_jobs()} == set(JOBS)


def test_get_job_raises_on_unknown() -> None:
    with pytest.raises(KeyError, match="Unknown job"):
        get_job("does-not-exist")


def test_plist_dict_has_required_launchd_keys() -> None:
    job = get_job("whatsapp-summary")
    payload = build_plist_dict(job)
    for key in (
        "Label",
        "ProgramArguments",
        "StartCalendarInterval",
        "StandardOutPath",
        "StandardErrorPath",
        "RunAtLoad",
    ):
        assert key in payload, f"missing key {key}"
    assert payload["Label"] == job.label
    assert payload["ProgramArguments"] == list(job.program)
    env = payload["EnvironmentVariables"]
    assert isinstance(env, dict) and env["HOME"]


def test_plist_roundtrips_through_plistlib(tmp_path: Path) -> None:
    job = get_job("whatsapp-summary")
    target = tmp_path / "test.plist"
    write_plist(job, target)
    with target.open("rb") as fh:
        loaded = plistlib.load(fh)
    assert loaded["Label"] == job.label
    assert loaded["StartCalendarInterval"] == dict(job.schedule)
    assert loaded["StandardOutPath"] == str(job.stdout_path)


def test_plist_install_path_under_launch_agents() -> None:
    job = get_job("whatsapp-summary")
    path = plist_install_path(job)
    assert path.parent == Path.home() / "Library" / "LaunchAgents"
    assert path.name == f"{job.label}.plist"


class _FakeSender:
    """Dependency-injected stand-in for Pushover.

    Records every call so tests can assert title/body/priority without `patch()`.
    """

    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.calls: list[dict[str, object]] = []

    def send_message(self, message: str, title: str | None = None, priority: int = 0) -> bool:
        self.calls.append({"message": message, "title": title, "priority": priority})
        return self.succeed


def test_notify_builds_title_and_returns_sender_status() -> None:
    sender = _FakeSender(succeed=True)
    ok = notify_mod.notify("whatsapp-summary", "ok", sender=sender)
    assert ok is True
    assert len(sender.calls) == 1
    call = sender.calls[0]
    assert call["title"] == "[LaunchJobs] whatsapp-summary: ok"
    assert call["priority"] == -1
    assert "Completed at" in str(call["message"])


def test_notify_uses_custom_body_when_provided() -> None:
    sender = _FakeSender()
    notify_mod.notify("whatsapp-summary", "fail", body="exit 7", sender=sender)
    assert sender.calls[0]["message"] == "exit 7"
    assert sender.calls[0]["title"] == "[LaunchJobs] whatsapp-summary: fail"


def test_notify_returns_false_when_sender_fails() -> None:
    sender = _FakeSender(succeed=False)
    assert notify_mod.notify("whatsapp-summary", "ok", sender=sender) is False
