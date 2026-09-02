# RingBeams

Daily health check for **Ring Beams** motion sensors and **Ring Alarm** contact/motion sensors, keypads, and range extenders.

Complements `RingSecurity/`, which covers Ring's cameras and doorbells via REST. Beams + Alarm state is only available on Ring's socket.io real-time channel, which no maintained Python library speaks — so this module shells out to a small Node.js sidecar (`fetch_status.js`) built on `ring-client-api` (dgreif/ring).

- **P1 alert** — battery below `battery_threshold_pct` (default 25%) OR Ring's own `batteryStatus == "warn"`
- **P0 alert** — `tamperStatus == "tamper"`
- **P0 alert** — sidecar auth failure (needs re-auth)
- **P1 alert** — partial sidecar failure (some locations returned errors) or generic sidecar error

Wired devices (base stations, adapters, keypads, range extenders on mains) are skipped: `batteryLevel: null` or `batteryStatus in {"none", "charging", "charged"}`. Contact sensors reporting `faulted: true` (a door currently open) are ignored — that's user state, not sensor health.

## Setup

### 1. Node.js runtime

```bash
brew install node          # macOS
# or apt-get install nodejs npm on Linux
```

### 2. Install sidecar deps

```bash
make node-deps
```
Creates `RingBeams/node_modules/` (gitignored). Runs `npm ci --ignore-scripts`:
`ring-client-api` pulls in `ffmpeg-for-homebridge`, whose postinstall downloads a
69 MB static ffmpeg from GitHub Releases. RingBeams never streams camera video, so
skipping install scripts halves the tree (150 MB -> 80 MB) and removes the only
network- and arch-dependent install step.

### 3. Reuse RingSecurity token

RingBeams reads `config/tokens/ring_auth_token.json` — the same OAuth token RingSecurity maintains. Do a one-time 2FA auth via RingSecurity if you haven't already:

```bash
uv run python RingSecurity/ring_manager.py auth
```

If the token later expires, RingBeams emits a P0 "Ring: Auth Required" Pushover; re-run the RingSecurity auth command.

### 4. Pushover token

Reuses the `Ring Security` token slot in `config/local.yaml` (same app as RingSecurity):
```yaml
pushover:
  tokens:
    Ring Security: <your-pushover-app-token>
```

## Known failure: missing `node_modules`

`node_modules/` is gitignored, so **any fresh clone or re-clone has a working Python
side and no sidecar deps at all**. This bit the prod host on 2026-08-30: the checkout
was replaced, the untracked directory went with it, and `git pull && uv sync` has no
step that brings it back. Node then died at module load and its
`ERR_MODULE_NOT_FOUND` stack became the Pushover body.

`beams_manager` now pre-flights for the package and raises a one-line remedy instead.
Fix is always `make node-deps`.

Setting `NODE_PATH` will **not** rescue this. `fetch_status.js` is `"type": "module"`,
and per [Node's ESM docs](https://nodejs.org/api/esm.html) *"`NODE_PATH` is not part of
resolving `import` specifiers"* -- it applies only to CommonJS `require()`. Only a real
`node_modules/` on the resolution walk works.

## Daily run

```bash
uv run python RingBeams/beams_manager.py check 2>&1 | tee /tmp/ring_beams.log
```

## Cron

```
0 9 * * * cd $HOMELY_VIBES && uv run python RingBeams/beams_manager.py check >> ~/logs/ring_beams.log 2>&1
```

Node must be on `PATH` inside the cron env. If cron can't find `node`, add to the top of your crontab:
```
PATH=/opt/homebrew/bin:/usr/bin:/bin
```
(Adjust for Linux — usually `/usr/local/bin` or `/usr/bin`.)

## Tests

```bash
uv run python -m pytest RingBeams -v
```
Sidecar subprocess is mocked with a tiny `sh` script for the happy-path / auth-error tests — no `patch()` on production code.

## Architecture

```
cron ──> beams_manager.py ──subprocess──> fetch_status.js ──socket.io──> Ring
             │                                    │
             │ parses JSON stdout                 │ authenticates via refresh_token
             └──> Pushover alerts                 └──> writes rotated refresh_token back
```

The sidecar exits promptly (~3s on your account) after emitting one JSON burst. It also writes any rotated refresh_token back to the same file, preserving the Python OAuth JSON envelope.
