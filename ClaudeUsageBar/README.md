# ClaudeUsageBar

A macOS menu bar app that shows your Claude Code plan usage — the same
5-hour session limit and 7-day (weekly) limit the `/usage` slash command
shows inside an interactive `claude` session — without opening a terminal.

Not sandboxed, no Dock icon (`LSUIElement`), no Xcode project — it's a plain
Swift Package Manager executable wrapped into a minimal `.app` bundle so it
can be launched from Finder/Spotlight/login items like a normal app.

## How it works

- **Auth**: reads the OAuth access token the `claude` CLI already stores in
  the macOS Keychain under the service name `Claude Code-credentials` (the
  bare name, no hash suffix — the hash-suffixed siblings
  `Claude Code-credentials-<hash>` are per-workspace MCP OAuth caches for
  third-party integrations, not the Anthropic API token; confirmed via
  `--probe-keychain`, see below). The payload is
  `{"claudeAiOauth": {"accessToken": ..., "expiresAt": ..., ...}}`.
  First read triggers a one-time macOS Keychain consent prompt — choose
  "Always Allow" so it doesn't ask again.
- **Data**: calls `GET https://api.anthropic.com/api/oauth/usage` with that
  bearer token — the same endpoint the CLI's `/usage` command calls
  (reverse-engineered from the installed `claude` binary via `strings`; not
  publicly documented). Response looks like:
  ```json
  {
    "five_hour": {"utilization": 77.0, "resets_at": "2026-08-14T04:49:59.72Z"},
    "seven_day": {"utilization": 27.0, "resets_at": "2026-08-18T04:59:59.72Z"},
    "seven_day_opus": null,
    "seven_day_sonnet": null
  }
  ```
  `utilization` is already a 0-100 percent, `resets_at` is ISO-8601.
  `seven_day_opus`/`seven_day_sonnet` are only populated on `max`/`team`
  plans. `spend.used`/`spend.limit` are minor-unit integers (cents) plus an
  `exponent`, so divide by `10^exponent` for dollars. The response carries
  further fields (per-channel overage, upgrade paths) not surfaced yet.
- **UI**: `NSStatusItem` menu bar title (`5h 42% · 7d 18%`), dropdown shows
  the full breakdown with reset times, usage-credit spend against its limit,
  a link to raise that limit, a manual refresh, and a quit item.
  Polls every minute.

## Build & run

```bash
swift build                      # debug build, for development
.build/debug/ClaudeUsageBar      # run in foreground (Ctrl-C to quit)

./Scripts/build_app.sh           # release build wrapped as ClaudeUsageBar.app
open ClaudeUsageBar.app
```

## Diagnostics

```bash
.build/debug/ClaudeUsageBar --probe-keychain   # lists candidate Keychain items and their JSON *keys* only (never values)
.build/debug/ClaudeUsageBar --probe-usage      # one-shot fetch + print, no menu bar UI
CLAUDE_USAGE_DEBUG=1 .build/debug/ClaudeUsageBar --probe-usage  # also dumps the raw response body to stderr
```

## Known limitations (v1)

- If the access token is expired and needs a refresh, this app does not
  reimplement the OAuth refresh flow — it just shows "Claude: —" with a
  hint to run `claude` once (which refreshes it, since it owns the
  Keychain item).
- No auto-launch-at-login wiring yet — open the `.app` manually, or add it
  to System Settings → General → Login Items.
- No WidgetKit desktop widget — this is menu-bar only.
