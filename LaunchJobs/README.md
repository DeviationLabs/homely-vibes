# LaunchJobs

One CLI for every homely_vibes-owned macOS `launchd` job. Render plists,
bootstrap them into the user's GUI domain, query status, tail logs.

## Quick start

```bash
# What's defined? What's loaded?
uv run python -m LaunchJobs.launchjobs list

# Install + bootstrap a job (evicts any legacy plists declared in the JobSpec)
uv run python -m LaunchJobs.launchjobs install whatsapp-summary

# Force a run now
uv run python -m LaunchJobs.launchjobs trigger whatsapp-summary

# Tail logs
uv run python -m LaunchJobs.launchjobs logs whatsapp-summary --tail 50
uv run python -m LaunchJobs.launchjobs logs whatsapp-summary --err --tail 50

# Detailed launchctl print output
uv run python -m LaunchJobs.launchjobs status whatsapp-summary

# Run the wrapper script directly, bypassing launchd (useful for debugging)
uv run python -m LaunchJobs.launchjobs run whatsapp-summary

# Tear down
uv run python -m LaunchJobs.launchjobs uninstall whatsapp-summary
```

## Adding a new job

1. Add a file under `LaunchJobs/jobs/` exposing a module-level `JOB: JobSpec`.
2. Add an `import` for it in `LaunchJobs/jobs/registry.py` (`_load_all_jobs`).
3. Give the job its **own Pushover application** and register the token
   in `config/local.yaml` under `pushover.tokens.<JobKey>`. Each job has
   its own app so rate limits and revocations stay isolated (this mirrors
   the `RachioFlume` convention).
4. If you're migrating a plist that previously lived elsewhere, list its
   old `Label` in `legacy_labels` so `install` bootouts and backs it up
   automatically.

## Jobs

### whatsapp-summary

Runs daily; invokes `pi -p "/productivity:whatsapp-summary"` and sends a
Pushover ping (app: `WhatsAppSummary`) on success, failure, or
WhatsApp-not-running skip.

Schedule, log paths configured under `launch_jobs.whatsapp_summary` in
`config/default.yaml`.

## Design notes

- Uses modern `launchctl bootstrap / bootout / kickstart` verbs against the
  `gui/<uid>` domain — avoids the deprecated `load / unload / start`.
- Plists are emitted via stdlib `plistlib` (typed, properly escaped) rather
  than templated XML.
- Each `JobSpec` is frozen and self-describing; CLI commands operate purely
  on the registry, no per-job switch statements.
