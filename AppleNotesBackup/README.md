# AppleNotesBackup

Backs up **Apple Notes** into a dedicated **private git repo** so accidentally
deleted (or edited-away) notes are always recoverable. Each run exports every
note, mirrors the current state into the repo as one HTML file per note, commits,
and pushes. Git history is the time machine.

## Why this design

- **AppleScript, not `NoteStore.sqlite`.** Notes are stored as gzip-compressed
  protobuf blobs in a private schema that changes across macOS versions. We go
  through Notes.app's scripting interface (`export_notes.applescript`) and read
  each note's rendered **HTML `body`** — lossless for text, lists, tables, and
  checklists, and stable across OS upgrades.
- **One HTML file per note, mirrored into git.** Each run makes the working tree
  match Notes exactly (deleting files for notes that vanished), then commits.
  Deleting the working file is safe — every past version stays in git history.
- **Hybrid filenames** `‹slug›__‹short_id›.html`. The `short_id` (an 8-hex-char
  fingerprint of the note's stable id) anchors identity, so renaming a note in
  Notes.app shows up as a git **edit**, not delete+add. Without it, every rename
  would look like an accidental delete and bury the real ones.

## One-time setup (you own this)

1. **Create the private backup repo** (never public — these are your notes):
   ```bash
   REPO="$HOME/AppleNotesBackup"          # wherever you want the backup to live
   mkdir -p "$REPO" && git -C "$REPO" init -b main
   # then create a PRIVATE GitHub remote and wire it up, e.g.:
   gh repo create <your-user>/<private-repo> --private --source "$REPO" --remote origin
   ```
2. **Point config at it.** Defaults live in `config/default.yaml` under
   `apple_notes_backup:` (see that block for every key). Override the per-host
   values in `config/local.yaml` (gitignored):
   ```yaml
   apple_notes_backup:
     backup_repo_dir: <absolute path to the repo you created above>
     git_remote: origin      # set "" to commit locally without pushing
     git_branch: main
   ```
3. **Grant Automation permission.** The first run triggers a macOS prompt:
   *"Terminal wants to control Notes."* Allow it (System Settings → Privacy &
   Security → Automation).

## Usage

```bash
# See what would be backed up — no writes, no commits (safe first run):
uv run python AppleNotesBackup/notes_backup.py --dry-run 2>&1 | tee /tmp/anb.log

# Real backup: export → mirror → commit → push:
uv run python AppleNotesBackup/notes_backup.py 2>&1 | tee /tmp/anb.log
```

On failure the script sends a **Pushover P1** ("Apple Notes backup failed") — a
silently non-running backup is worse than a noisy one.

## Recovering a deleted note

Notes live under `‹Folder›/‹slug›__‹short_id›.html`.

```bash
cd "$backup_repo_dir"    # the path you set in config

# Find commits where a note was deleted:
git log --oneline --diff-filter=D -- '**/grocery-list__*.html'

# Restore the last version before deletion (^ = the commit's parent):
git show <deleting-commit>^:MyFolder/grocery-list__ab12cd34.html > recovered.html
open recovered.html      # then copy/paste back into Notes.app
```

To browse everything as of a point in time: `git checkout <commit>` in a scratch
clone.

## Scheduling

Per repo convention, macOS scheduled jobs live in **Claude Code routines**, not in
this repo (the old `launchd` module was removed). Set up a daily routine that runs:

```bash
cd /path/to/homely_vibes && \
  uv run python AppleNotesBackup/notes_backup.py >> ~/logs/apple_notes_backup.log 2>&1
```

## Folder layout

Files mirror your **full Notes folder hierarchy**:
`‹Parent›/‹Child›/…/‹slug›__‹short_id›.html`. The exporter walks folders top-down
and recursively (`folders of folder`), threading the accumulated path — so
subfolders nest correctly and same-named folders are disambiguated by their real
parent (e.g. a top-level `Archive/` vs a nested `Work/Archive/` vs
`Projects/Archive/`). We read only *downward*; reading a folder/note's parent via
`container` errors (-1728) on items reached through a top-level collection.

- **Empty folders produce no directory.**
- **"Recently Deleted" is included by design** — a note you deleted but haven't
  purged (30-day window) still gets captured, adding a safety net for deletes that
  happen between runs.

## Limitations (v1)

- **Attachments: metadata only.** Images, drawings, and scanned PDFs are recorded
  by count in each note's header comment but not exported as files. Full
  attachment export is future work.
- Runs on the Mac where Notes.app lives (notes are local); not a prod-host job.
