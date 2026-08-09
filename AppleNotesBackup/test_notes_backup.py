"""Tests for AppleNotesBackup — real subprocess + real git, no patching."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from AppleNotesBackup.notes_backup import (
    RECORD_SEP,
    UNIT_SEP,
    Note,
    commit_and_push,
    folder_relpath,
    note_filename,
    parse_stream,
    prune_stale,
    run_export,
    write_notes,
)


def _record(note_id: str, folder: str, name: str, modified: str, att: str, body: str) -> str:
    return UNIT_SEP.join([note_id, folder, name, modified, att, body]) + RECORD_SEP


def _note(
    note_id: str = "x-coredata://A/ICNote/p1", folder: str = "Notes", name: str = "Hi"
) -> Note:
    return Note(
        id=note_id,
        folder=folder,
        name=name,
        modified="2026-01-01T00:00:00",
        attachment_count=0,
        body="<div>hi</div>",
    )


# ── parse_stream ──────────────────────────────────────────────────────────────


def test_parse_stream_roundtrip_with_awkward_body() -> None:
    # Body deliberately contains newlines and commas — proves the control-char
    # delimiters survive content that would break line/CSV parsing.
    body = "<div>line one,\nline two\twith tab</div>"
    raw = _record("id-1", "Personal", "Grocery List", "2026-01-01T00:00:00", "2", body)
    notes = parse_stream(raw)
    assert len(notes) == 1
    n = notes[0]
    assert n.id == "id-1"
    assert n.folder == "Personal"
    assert n.name == "Grocery List"
    assert n.attachment_count == 2
    assert n.body == body


def test_parse_stream_skips_malformed_record() -> None:
    good = _record("id-1", "Notes", "Good", "2026-01-01T00:00:00", "0", "<p>ok</p>")
    malformed = "only" + UNIT_SEP + "two-fields" + RECORD_SEP
    notes = parse_stream(good + malformed)
    assert [n.id for n in notes] == ["id-1"]


def test_parse_stream_empty() -> None:
    assert parse_stream("") == []


# ── note_filename (hybrid identity) ───────────────────────────────────────────


def test_note_filename_is_html() -> None:
    assert note_filename(_note()).endswith(".html")


def test_note_filename_stable_across_rename() -> None:
    # Same id, different name → the short_id anchor is unchanged, so git sees an
    # edit rather than delete+add. Suffix must match; slug may differ.
    a = note_filename(_note(name="Grocery List"))
    b = note_filename(_note(name="Groceries"))
    assert a.split("__", 1)[1] == b.split("__", 1)[1]
    assert a != b


def test_note_filename_differs_by_id() -> None:
    a = note_filename(_note(note_id="x-coredata://A/ICNote/p1"))
    b = note_filename(_note(note_id="x-coredata://A/ICNote/p2"))
    assert a != b


def test_note_filename_caps_length() -> None:
    long_name = "word " * 200
    fname = note_filename(_note(name=long_name))
    slug = fname.split("__", 1)[0]
    assert len(slug) <= 80


# ── write_notes + prune_stale + commit_and_push (real git repo) ───────────────


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.io"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    return tmp_path


def test_folder_relpath_preserves_nesting() -> None:
    # Each component slugified independently; hierarchy kept (not flattened).
    assert folder_relpath("Archive/FB/FB UP").parts == ("Archive", "FB", "FB-UP")
    assert folder_relpath("Personal").parts == ("Personal",)
    assert folder_relpath("").parts == ("Notes",)


def test_write_notes_lays_out_by_nested_folder(repo: Path) -> None:
    n = _note(folder="Archive/FB", name="Trip Plan")
    written = write_notes([n], repo)
    rel = next(iter(written))
    assert rel.parts[:2] == ("Archive", "FB")  # nested dir preserved
    dest = repo / rel
    assert dest.exists()
    assert "Trip Plan" in dest.read_text(encoding="utf-8")  # metadata header


def test_prune_removes_vanished_notes_and_empty_dirs(repo: Path) -> None:
    keep = _note(note_id="keep", folder="Work", name="Keep Me")
    gone = _note(note_id="gone", folder="Archive", name="Delete Me")
    write_notes([keep, gone], repo)

    written = write_notes([keep], repo)  # second run: `gone` no longer exported
    pruned = prune_stale(repo, written)

    assert len(pruned) == 1
    assert not (repo / "Archive").exists()  # empty folder cleaned up
    assert (repo / next(iter(written))).exists()


def test_commit_skips_when_clean(repo: Path) -> None:
    write_notes([_note()], repo)
    assert commit_and_push(repo, "main", "") is not None  # first commit happens
    assert commit_and_push(repo, "main", "") is None  # nothing changed


def test_commit_counts_and_skips_push_without_remote(repo: Path) -> None:
    write_notes([_note(note_id="a", name="A"), _note(note_id="b", name="B")], repo)
    msg = commit_and_push(repo, "main", "")  # empty remote → no push attempted
    assert msg is not None and "new" in msg
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline"], capture_output=True, text=True
    ).stdout
    assert msg.split(":")[0] in log or "backup" in log


# ── run_export (injected runner, no patching) ─────────────────────────────────


def test_run_export_returns_stdout_on_success() -> None:
    def fake_runner(*_a: object, **_k: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="STREAM", stderr="")

    assert run_export(timeout=5, runner=fake_runner) == "STREAM"


def test_run_export_raises_on_failure() -> None:
    def fake_runner(*_a: object, **_k: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_export(timeout=5, runner=fake_runner)
