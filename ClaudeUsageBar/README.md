# ClaudeUsageBar

A macOS menu bar app that shows your Claude Code plan usage — the same
5-hour session limit and 7-day (weekly) limit the `/usage` slash command
shows inside an interactive `claude` session — without opening a terminal.

Not sandboxed, no Dock icon (`LSUIElement`), no Xcode project — it's a plain
Swift Package Manager executable wrapped into a minimal `.app` bundle so it
can be launched from Finder/Spotlight/login items like a normal app.

## How it works

- **Auth**: the app **owns its own Keychain item**, `com.deviationlabs.ClaudeUsageBar`,
  the way every well-behaved macOS app does (`Chrome Safe Storage`,
  `Slack Safe Storage`, …). Reads go, in order: in-memory cache → own item →
  bootstrap from the `claude` CLI's `Claude Code-credentials` item via
  `/usr/bin/security`, whose result is then written into our own item. A 401
  from the API drops *both* the memory cache and the own item, so the next tick
  re-bootstraps rather than replaying a token the server already rejected.
  See "Keychain access" below for why this shape is the only durable one.
  The hash-suffixed siblings `Claude Code-credentials-<hash>` are per-workspace
  MCP OAuth caches (`{"mcpOAuth": …}`) with no `accessToken` at any level, and
  are never consulted.
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
- **UI**: `NSStatusItem` menu bar title (`58% 2h · 82% 3d`) — 5-hour window
  first, then 7-day. The title reports what is **left**, not what was consumed:
  budget remaining (`100 - utilization`) and time until reset, shown as the
  largest non-zero unit only (`3d` / `2h` / `47m`). Time is floored, so it
  understates rather than overstates what's left; resolution sharpens to
  minutes exactly as a window runs low. An absent `five_hour` window means
  nothing has been spent yet and renders `100% 5h`. The dropdown keeps the
  opposite convention — percent *consumed* plus a precise reset time: absolute
  wall-clock with a two-unit countdown (`resets 11:20 PM (in 1h 43m)`,
  weekday-prefixed when the reset falls on another day). The title stays coarse
  because it competes for menu bar width; the dropdown is where there is room.
  The dropdown also adds usage-credit spend against its limit, a link to raise
  that limit, a manual refresh, a refresh-interval picker, and a quit item.
- **Failure states**: a failed refresh never blanks a working display — the last
  good numbers stay, marked `⚠︎`, with the reason in the dropdown. "Run `claude`
  once to sign in" appears only when the credentials are genuinely absent or
  expired; a *blocked* Keychain read says so instead and notes that it is
  retrying, because telling you to sign in when you already are is a dead end.
- **Refresh cadence**: 180s by default, changeable from the dropdown
  (30s / 1 / 3 / 5 / 10 / 30 min) and persisted in `UserDefaults`, so the
  choice survives relaunch. The default is deliberately slow: the 5-hour bar
  moves ~0.5%/min even at a heavy sustained pace and the 7-day bar far less,
  so polling faster mostly spends requests redrawing an unchanged number.

## Build & run

```bash
swift build                      # debug build, for development
.build/debug/ClaudeUsageBar      # run in foreground (Ctrl-C to quit)

./Scripts/build_app.sh           # release build wrapped as ClaudeUsageBar.app
open ClaudeUsageBar.app
```

## Expired tokens

The CLI's access token lives **8 hours** and is refreshed only when `claude`
actually runs. Any longer gap — overnight, a quiet weekend — leaves the token
expired, and the widget has nothing valid to call the API with. Diagnosed from
the unified log in
`homely-vibes-archived#250` (closed; private archive): the poll
timer was firing perfectly every 180s and correctly reporting an expired
upstream token for ~25 hours, then recovered on its own the moment a `claude`
session rotated it. No restart was ever the fix.

Since we cannot refresh (rotation would log the CLI out — see "Known
limitations"), the app asks **the CLI** to do it: on an expired token it spawns

```
claude auth status
```

which is non-interactive, prints no secrets, returns in ~0.2s, and whose
refresh path is expiry-driven (`if (!force && !isExpired(expiresAt)) return
"not_needed"`). The CLI performs the refresh under its own `oauth_refresh_lock`,
serialised against its other sessions rather than racing them, and writes its
own Keychain item — we never do.

Three deliberate constraints:

- **Only `.expired` triggers a nudge.** `.notFound` means there is nothing to
  refresh; `.accessDenied` means the read was blocked. Spawning the CLI helps
  neither.
- **Throttled to one attempt per 10 minutes.** An expired token stays expired
  until the CLI refreshes it, so an unthrottled nudge would fork a 256MB binary
  on every 180s poll for the whole window.
- **Resolved by absolute path.** A GUI app inherits a minimal `PATH`
  (`/usr/bin:/bin:/usr/sbin:/sbin`) with no Homebrew on it, so `claude` is
  found via an ordered candidate list, not by name. Check yours with
  `--probe-nudge`.

## Keychain access

macOS gates a Keychain read through **two** independent lists: the item's ACL
application list *and* its **partition list**. Both must admit the caller.

Earlier versions read the CLI's `Claude Code-credentials` item directly and
could never stop prompting, for two compounding reasons:

1. Grants are recorded in the partition list against a `cdhash:` — which changes
   on every rebuild. (Signing with a certificate stabilises the *designated
   requirement*, which is the ACL half; it does nothing for the partition half.
   That distinction is what the previous version of this document missed.)
2. The `claude` CLI rewrites that item on every token rotation — its `mdat`
   advances while `cdat` stays put — and each rewrite resets both lists. So no
   grant could outlive a single token cycle.

The fix is to stop borrowing someone else's item. Every clean item in a login
keychain belongs to its reader:

| Item | Partition list | ACL entries |
|---|---|---|
| `Chrome Safe Storage` | `teamid:EQHXZ8M8AV` | 1 |
| `Slack Safe Storage` | `teamid:BQR82RBBHL` | 1 |
| `com.deviationlabs.ClaudeUsageBar` | `teamid:656D6H7G24` | 1 |

Because the app creates the item, macOS puts its **team ID** — stable across
every rebuild — in the partition list, and nothing else ever rewrites it. The
CLI's item is still the source of truth for the token, but it is only ever read
through `/usr/bin/security`, which carries `apple-tool:` in the partition list
of every one of these items and survives each rotation.

Verify the shape with:

```bash
security dump-keychain -a 2>/dev/null | grep -A12 com.deviationlabs.ClaudeUsageBar
```

You want `teamid:` and **not** `cdhash:` in the partition list. A `cdhash:` there
means the item was created by an ad-hoc-signed build (see below) and will
re-prompt after the next rebuild; delete it with
`security delete-generic-password -s com.deviationlabs.ClaudeUsageBar` and
re-bootstrap from a signed build.

## Code signing

`build_app.sh` signs the bundle. This is not about Gatekeeper — an ad-hoc
signature has no certificate and therefore no team ID, so an item created by
such a build gets a `cdhash:` partition entry and the prompt comes back on every
rebuild. A certificate gives both a stable designated requirement:

```
designated => identifier "com.deviationlabs.ClaudeUsageBar"
  and anchor apple generic
  and certificate leaf[subject.CN] = "Apple Development: ..."
```

and a stable `teamid:` partition entry. Verify with
`codesign -d -r- ClaudeUsageBar.app`.

Note that `swift build` alone produces an ad-hoc binary, so the debug executable
and the signed `.app` do not share a grant. Develop with `--probe-keychain`;
trust the `.app` for the durable behaviour.

The script picks the first **Apple Development** identity in your keychain. With
no Apple Developer account, create a self-signed certificate once — Keychain
Access → *Certificate Assistant* → *Create a Certificate…*, name it
`ClaudeUsageBar Self-Signed`, type *Code Signing*, then re-run the script.
Override the name with `CLAUDE_USAGE_BAR_SIGN_IDENTITY`. With neither, the build
still succeeds but warns and falls back to ad-hoc.

Changing the signing identity invalidates existing grants, so expect one more
consent prompt after the first signed build.

## Diagnostics

```bash
.build/debug/ClaudeUsageBar --probe-keychain   # reports which source served the token (cache / own item / bootstrap); never prints a secret
.build/debug/ClaudeUsageBar --probe-usage      # one-shot fetch + print, no menu bar UI
.build/debug/ClaudeUsageBar --probe-nudge      # can the `claude` CLI be located and driven? shows each candidate path
CLAUDE_USAGE_DEBUG=1 .build/debug/ClaudeUsageBar --probe-usage  # also dumps the raw response body to stderr
```

`--probe-nudge` is safe to run at any time: on a still-valid token the CLI's
refresh short-circuits to "not_needed", so it only proves reachability.

The running app also logs every poll tick (success/failure/reason) and sleep/wake
events to the unified log, subsystem `com.deviationlabs.ClaudeUsageBar`,
category `refresh`:

```bash
log show --predicate 'subsystem == "com.deviationlabs.ClaudeUsageBar"' --last 3d
log stream --predicate 'subsystem == "com.deviationlabs.ClaudeUsageBar"'   # live
```

Added after a 2026-08 incident (`homely-vibes-archived#250`) where the menu
bar stayed stuck on `credentials expired` for 60+ hours despite the underlying
CLI token being valid again — a restart fixed it, but the root cause (leading
suspect: macOS App Nap throttling the repeating `Timer` on a long-lived,
no-window accessory app) was never confirmed. If it recurs, `log show` now has
the tick-by-tick history — specifically the gap between ticks
(`gapSinceLastTick`) and whether a `willSleep`/`didWake` pair brackets the
stall — to tell App Nap apart from a genuine, repeated backend/keychain
failure. See the issue for the fix candidates once diagnosed.

## Troubleshooting

### The menu bar says "Claude: —"

Read the dropdown — it now names the cause, and only one of them is fixed by
signing in:

| Dropdown says | Meaning | Fix |
|---|---|---|
| `no Claude Code credentials on this Mac` | No `Claude Code-credentials` item exists | Run `claude` once |
| `credentials expired` | The CLI's token is past `expiresAt` | Usually self-healing — the app nudges the CLI to refresh (see "Expired tokens"). Persists only if the nudge cannot find or drive `claude`; check `--probe-nudge` |
| `Keychain access denied` / `keychain locked` | The token exists and is fine; the *read* was refused | Unlock the login keychain; see below |
| `credentials unreadable` | Payload did not parse | File a bug — the CLI's schema likely moved |

A working display is never blanked by a failed refresh: the last good numbers
stay with a `⚠︎` and the reason. So "Claude: —" means it has *never* succeeded
since launch.

### The Keychain prompt came back

It should not. If it does, find out which build created our item:

```bash
security dump-keychain -a 2>/dev/null | grep -A12 com.deviationlabs.ClaudeUsageBar
```

- `partition: teamid:656D6H7G24` — correct, stable across rebuilds.
- `partition: cdhash:…` — the item was created by an **ad-hoc** build (plain
  `swift build`, no certificate, therefore no team ID). It will re-prompt after
  every rebuild. Repair:

  ```bash
  security delete-generic-password -s com.deviationlabs.ClaudeUsageBar
  ./Scripts/build_app.sh && open ClaudeUsageBar.app   # re-bootstrap from the signed app
  ```

### Debugging the original prompt loop

Two facts are worth keeping, because they are not obvious and cost real time:

- **A Keychain read is gated by two lists, not one.** The ACL application list
  *and* the partition list. Fixing only the designated requirement (the ACL
  half) leaves a `cdhash:` pinned in the partition half, and the prompt keeps
  returning. `codesign -d -r-` tells you nothing about the partition list —
  only `security dump-keychain -a` does.
- **`cdat` vs `mdat` on an item tells you who is rewriting it.** On
  `Claude Code-credentials`, `cdat` sits at the day you first signed in while
  `mdat` tracks the present: the CLI rewrites it on every token rotation, and
  each rewrite resets both access lists. That is why no grant against *that*
  item could ever be durable, and why this app owns its own instead.

## Known limitations (v1)

- This app does not run the OAuth refresh itself, and must not. Anthropic
  **rotates the refresh token on use** — confirmed by decompiling the `claude`
  binary: the refresh response carries a new `refreshToken` *and* a
  `refreshTokenExpiresAt`, and the CLI's write-back aborts if the stored token
  changed underneath it (`if (y && y !== c) …`), a guard that only makes sense
  when the old token dies on use. Spending that single-use token here would
  leave the CLI holding a dead one, i.e. log you out. Instead the app *nudges*
  the CLI — see "Expired tokens" below.
- No auto-launch-at-login wiring yet — open the `.app` manually, or add it
  to System Settings → General → Login Items.
- The signing identity is resolved at build time from whatever is in your
  keychain, so a bundle built on one machine won't carry another's grant.
- No WidgetKit desktop widget — this is menu-bar only.
