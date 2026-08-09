#!/usr/bin/env python3
"""Apple Notes → private git repo backup.

Exports every Apple Note via AppleScript (Notes.app scripting interface, not the
private NoteStore.sqlite blob format) and mirrors them into a dedicated private
git repo as one HTML file per note. Each run makes the working tree match the
current state of Notes, then commits — so git history is the recovery mechanism:
an accidentally-deleted note lives on in past commits.

    recover a deleted note:
        cd <backup_repo_dir>
        git log --oneline --diff-filter=D -- '**/grocery-list__*.html'
        git show <commit>^:Personal/grocery-list__ab12cd34.html > recovered.html

Usage:
    uv run python AppleNotesBackup/notes_backup.py            # export + commit + push
    uv run python AppleNotesBackup/notes_backup.py --dry-run  # export + report, no writes
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lib.config import get_config
from lib.logger import get_logger
from lib.MyPushover import Pushover

logger = get_logger(__name__)

# Delimiters emitted by export_notes.applescript. ASCII control chars that
# effectively never appear in note HTML, so parsing is unambiguous even when a
# note body contains newlines, commas, or tabs.
RECORD_SEP = "\x1e"  # ASCII 30 — between notes
UNIT_SEP = "\x1f"  # ASCII 31 — between fields
_N_FIELDS = 6  # id, folder, name, modified, attachment_count, body

_APPLESCRIPT = Path(__file__).with_name("export_notes.applescript")
_FILENAME_MAXLEN = 80  # cap the readable portion of a filename

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Note:
    """One exported Apple Note."""

    id: str
    folder: str
    name: str
    modified: str
    attachment_count: int
    body: str  # HTML


# ── export + parse ────────────────────────────────────────────────────────────


def run_export(
    timeout: int,
    applescript: Path = _APPLESCRIPT,
    runner: Runner = subprocess.run,
) -> str:
    """Run the AppleScript exporter and return its raw delimited stdout.

    `runner` is injected so tests can supply a fake exporter without patching.
    """
    result = runner(
        ["osascript", str(applescript)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"osascript export failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return str(result.stdout)


def parse_stream(raw: str) -> list[Note]:
    """Parse the delimited AppleScript stream into Note records."""
    notes: list[Note] = []
    for record in raw.split(RECORD_SEP):
        if not record.strip():
            continue
        fields = record.split(UNIT_SEP)
        if len(fields) != _N_FIELDS:
            logger.warning("skipping malformed record with %d fields", len(fields))
            continue
        note_id, folder, name, modified, att_count, body = fields
        notes.append(
            Note(
                id=note_id,
                folder=folder,
                name=name,
                modified=modified,
                attachment_count=int(att_count) if att_count.isdigit() else 0,
                body=body,
            )
        )
    return notes


# ── filename identity ─────────────────────────────────────────────────────────


def slugify(text: str) -> str:
    """Filesystem-safe component: keep alnum/space/dash/underscore, collapse rest."""
    cleaned = "".join(c if (c.isalnum() or c in " -_") else "-" for c in text.strip())
    collapsed = "-".join(cleaned.split())
    return collapsed.strip("-.") or "untitled"


def short_id(note_id: str) -> str:
    """Stable 8-hex-char fingerprint of a note's id — same note, same value forever."""
    return hashlib.sha1(note_id.encode("utf-8")).hexdigest()[:8]  # noqa: S324


def note_filename(note: Note) -> str:
    """Return the .html filename for a note: <slugified-name>__<short_id>.html.

    Hybrid identity: the short_id anchors the file across renames, so renaming a
    note in Notes.app reads as a git edit (not delete+add) and genuine deletes
    stay distinguishable from rename churn. The slug keeps files human-browsable.
    """
    slug = slugify(note.name)[:_FILENAME_MAXLEN]
    return f"{slug}__{short_id(note.id)}.html"


# ── mirror into the repo ──────────────────────────────────────────────────────


def _render(note: Note) -> str:
    """Wrap the note body in an HTML doc with a metadata header comment."""
    meta = (
        f"<!-- apple-note\n"
        f"     id: {note.id}\n"
        f"     folder: {note.folder}\n"
        f"     name: {note.name}\n"
        f"     modified: {note.modified}\n"
        f"     attachments: {note.attachment_count}\n"
        f"-->\n"
    )
    return meta + note.body + "\n"


def folder_relpath(folder: str) -> Path:
    """Map a "/"-separated Notes folder path to a nested dir, slugifying each part.

    Slugify per-component (not the whole string) so the hierarchy is preserved —
    slugifying "Archive/FB" as one string would collapse the "/" and flatten it.
    """
    parts = [slugify(p) for p in folder.split("/") if p]
    return Path(*parts) if parts else Path("Notes")


def write_notes(notes: list[Note], repo: Path) -> set[Path]:
    """Write each note to <repo>/<folder-path>/<note_filename>. Returns relative paths."""
    written: set[Path] = set()
    for note in notes:
        rel = folder_relpath(note.folder) / note_filename(note)
        dest = repo / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_render(note), encoding="utf-8")
        written.add(rel)
    return written


def prune_stale(repo: Path, keep: set[Path]) -> list[Path]:
    """Delete tracked *.html files no longer present in Notes (recovery lives in git history).

    Also removes directories left empty afterward. Returns the pruned relative paths.
    """
    pruned: list[Path] = []
    for path in repo.rglob("*.html"):
        if ".git" in path.parts:
            continue
        rel = path.relative_to(repo)
        if rel not in keep:
            path.unlink()
            pruned.append(rel)
    for folder in sorted(repo.rglob("*"), reverse=True):
        if folder.is_dir() and ".git" not in folder.parts and not any(folder.iterdir()):
            folder.rmdir()
    return pruned


# ── git ───────────────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _push_if_ahead(repo: Path, branch: str, remote: str) -> None:
    """Push any local commits the remote is missing.

    Covers the case where a prior run committed but its push failed: on a later
    run with no note changes the tree is clean, so without this the unpushed
    commit would never be retried and the off-machine backup would silently stall.
    """
    if not remote:
        return
    try:
        ahead = _git(repo, "rev-list", "--count", f"{remote}/{branch}..HEAD").strip()
    except RuntimeError:
        ahead = "1"  # no remote-tracking ref yet (never pushed) → push
    if ahead != "0":
        _git(repo, "push", remote, branch)
        logger.info("pushed %s pending commit(s) to %s/%s", ahead, remote, branch)


def commit_and_push(repo: Path, branch: str, remote: str) -> str | None:
    """Stage all changes and commit if anything changed; push when `remote` is set.

    Returns the commit message, or None if the working tree was clean.
    """
    _git(repo, "add", "-A")
    status = _git(repo, "status", "--porcelain")
    if not status.strip():
        logger.info("no changes to back up")
        _push_if_ahead(repo, branch, remote)  # retry a prior run's unpushed commit
        return None

    added = changed = deleted = 0
    for line in status.splitlines():
        code = line[:2]
        if "D" in code:
            deleted += 1
        elif "A" in code or "?" in code:
            added += 1
        else:
            changed += 1

    message = f"backup: {added} new, {changed} changed, {deleted} deleted"
    _git(repo, "commit", "-m", message)
    logger.info(message)
    if remote:
        _git(repo, "push", remote, branch)
        logger.info("pushed to %s/%s", remote, branch)
    return message


# ── orchestration ─────────────────────────────────────────────────────────────


def backup(dry_run: bool = False) -> None:
    cfg = get_config().apple_notes_backup

    raw = run_export(cfg.osascript_timeout_seconds)
    notes = parse_stream(raw)
    logger.info("exported %d notes", len(notes))

    if dry_run:
        # Read-only preview: never touches (or requires) the backup repo, so this
        # is safe to run before the one-time repo setup exists.
        folders = sorted({n.folder for n in notes})
        logger.info("dry-run: %d notes across folders: %s", len(notes), ", ".join(folders))
        return

    repo = Path(cfg.backup_repo_dir).expanduser()
    if not (repo / ".git").is_dir():
        raise RuntimeError(
            f"{repo} is not a git repo. Create a *private* one first: "
            f"mkdir -p {repo} && git -C {repo} init -b {cfg.git_branch}"
        )

    written = write_notes(notes, repo)
    pruned = prune_stale(repo, written)
    if pruned:
        logger.info("pruned %d notes no longer in Notes.app", len(pruned))
    commit_and_push(repo, cfg.git_branch, cfg.git_remote)


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up Apple Notes into a private git repo")
    parser.add_argument("--dry-run", action="store_true", help="export and report; no writes")
    args = parser.parse_args()

    try:
        backup(dry_run=args.dry_run)
    except Exception as e:
        logger.error("Apple Notes backup failed: %s", e)
        # Backup silently not running is bad: actionable within hours -> P1.
        Pushover().send_message(str(e), title="Apple Notes backup failed", priority=1)
        sys.exit(1)


if __name__ == "__main__":
    main()
