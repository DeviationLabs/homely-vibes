# Rachio-Flume Water Tracking Integration

A Python integration that connects Rachio irrigation controllers with Flume water monitoring devices to track zone-specific water usage and generate comprehensive reports.

## Features

- **Rachio Integration**: Monitor active zones and watering events
- **Flume Integration**: Track real-time water consumption across all devices
- **Data Correlation**: Match watering events with water usage patterns
- **Smart Hose Timer support** (`rachio_hose_client.py`, `hose_timer_processor.py`): Rachio Smart Hose Timer base stations exposed via `cloud-rest.rach.io` alongside the controller. Runs detected via `lastWateringAction` state polling; flow stats from Flume.
- **Usage Alerts** (`alert_engine.py`):
  - **Single dispatch per zone end**: One Pushover per zone end — `RachioFlume: Zone Report` (P-1) below anomaly threshold, `RachioFlume: Zone Anomaly` (P2) above. Never both. Includes runtime, avg GPM, `(thresh X.XX)` (computed anomaly threshold), Total, and Deviation line on anomalies.
  - **Zone anomaly detection**: Per-zone baselines under `rachio_flume.alerts.zone_anomaly.zone_thresholds`, keyed by device label then zone identifier (controller: stringified `zone_number`; hose-timer: valve name). Threshold formula: `avg_gpm + max(absolute_gpm, percent_above/100 × avg_gpm)`.
  - **Default flow rules** (whole-house, Flume-only): Pipe Break / High Flow / Mid Flow / Leak — P2 (emergency), at most once per day per rule. CV-based variance filter rejects spiky noise on low-flow rules.
  - **Cross-source suppression**: Controller-active OR hose-timer-active state suppresses Flume rules for `max_rule_duration + 10min` slack. Symmetric.
  - **Stale-zone monitor** (`stale_zone_checker.py`): P-1 heads-up if any enabled zone hasn't run within `stale_zone_days` (default 7). Daily dedup; hourly evaluation gate.
  - Mute support; P0 "all clear" on active→clear transition for sustained-flow rules.
- **Synthetic Simulator** (`simulate_alerts.py`): Replay scenarios through the alert engine without hitting real APIs or Pushover; wired into `test_alert_simulation.py`. See [TESTABILITY.md](TESTABILITY.md).
- **HTML Email Report**: Daily fixed-width table (via `<pre>` monospace) covering all zones — controllers and hose valves in one unified table. Per-zone anomaly threshold + alert-session count are surfaced alongside runtime / gallons / GPM.
- **Continuous Monitoring**: Automated data collection service
- **SQLite Storage**: Persistent data storage with session tracking

## Setup

### Credentials Configuration

Add your API credentials to `config/local.yaml`:

```yaml
# Rachio API credentials. Single api_key works for both controllers and hose timers.
# `type` selects the API surface:
#   - "controller": api.rach.io/1/public/device/*    (Smart Sprinkler Controller)
#   - "hose_timer": cloud-rest.rach.io/valve/*       (Smart Hose Timer base station)
# `id` is the deviceId (controllers) or baseStationId (hose timers).
rachio:
  api_key: abc123...
  devices:
    - {id: "5d11b1a5-...", label: "Rachio-Eden",       type: "controller"}
    - {id: "a632eacc-...", label: "Hose Drip Jasmine", type: "hose_timer"}

# Flume API credentials (get from https://portal.flumetech.com/#token)
flume:
  client_id: client-id...
  client_secret: client-secret...
  user_email: your-email@example.com
  password: your-password...
```

Run `uv run python RachioFlume/rfmanager.py list-devices` after setting
`api_key` to enumerate all controllers and hose-timer base stations the API
sees, then populate `devices` with the printed ids/labels.

**Note**: The credentials are sourced from `config/local.yaml` (gitignored) for security.

### Installation

From the project root directory:

```bash
uv sync
```

## Usage

All commands should be run from the RachioFlume directory.

### Recommended Workflow

1. **Start continuous data collection** (run in background)
2. **Check status** anytime to see active zones and flow rates  
3. **Generate reports** after collecting data for several days/weeks

### 🔄 Data Collection (Continuous Operation)

For best results, run the collector continuously to gather data over time:

```bash
# Start continuous collection in background (recommended)
nohup uv run python rfmanager.py collect > water_tracking.log 2>&1 &

# Or run in foreground (will stop when terminal closes)
uv run python rfmanager.py collect

# Custom collection intervals
uv run python rfmanager.py collect --interval 120    # Every 2 minutes
uv run python rfmanager.py collect --interval 600    # Every 10 minutes (default: 300)
```

**💡 Pro Tip**: Let the collector run for at least a week before tuning zone thresholds — needs a distribution of runs per zone to be meaningful.

### 📊 System Status (Check Anytime)

```bash
# See current active zone and real-time usage rate
uv run python rfmanager.py status
```

Example output:
```
==================================================
WATER TRACKING SYSTEM STATUS
==================================================
Active Zone: #11 - Z11 BB - Outer Perim
Current Usage Rate: 6.14 GPM
Recent Sessions (24h): 15
Last Rachio Collection: 2023-07-15T10:30:00
Last Flume Collection: 2023-07-15T10:35:00
==================================================
```

### 📈 Reports (After Data Collection)

Generate comprehensive reports once you have collected data:

```bash
# Generate period report (default: last 7 days)
uv run python rfmanager.py report

# Custom period report with specific end date and lookback days
uv run python rfmanager.py report --end-date 2023-07-15 --lookback 14

# Send report via HTML email
uv run python rfmanager.py report --email

# Raw data report with 5-minute intervals (Flume-only, no Rachio context)
uv run python rfmanager.py raw --hours 48
```

### 🚨 Usage Alerts

The collector evaluates two independent alert paths each polling cycle.
Config lives under `rachio_flume.alerts` in `config/default.yaml`,
overridable per-house in `config/local.yaml`. The block is split by scope:

- **`zone_anomaly`** — per-zone anomaly check (Rachio-sourced; fires at run end).
  Holds `threshold_mode`, `absolute_gpm`, `percent_above`, `min_runtime_minutes`,
  and `zone_thresholds`. Computes `threshold = avg_gpm + max(absolute_gpm, percent_above/100 × avg_gpm)`.
- **`default_flow_rules`** — whole-house sustained-flow rules (Flume only, no
  Rachio context). Pipe Break, High Flow, Mid Flow, Leak. Suppressed while any
  Rachio activity (controller OR hose-timer) is recent.
- **`stale_zone_days`** — heads-up threshold for the stale-zone monitor.

Key behaviors:

- **One Pushover per zone end** — `_send_zone_outcome` on both AlertEngine and
  HoseTimerProcessor picks `(title, priority)` based on whether measured flow
  exceeds the anomaly threshold. Either `RachioFlume: Zone Report` (P-1) OR
  `RachioFlume: Zone Anomaly` (P2). Never both. Anomaly variant adds a
  `Deviation: +X.XX GPM (Y%)` line. Both variants include `Total: N.N gal`.
- **Unified threshold value** — the `(thresh X.XX)` shown on every zone-end
  report is the computed anomaly trigger value, matching what actually fires.
- **Sustained-flow rules fire at P2** (emergency — retries until acked), at
  most once per day per rule. P-0 "all clear" on transition active → clear.
- **Final detector logic for sustained-flow rules** — implemented in
  [`AlertEngine._rule_matches`](alert_engine.py). A rule fires when both
  conditions hold across the trailing `duration_minutes` window:
  1. **Mean test** — `mean(values) ≥ rule.min_gpm`.
  2. **CV variance gate** — `cv = stddev / mean ≤ max_cv(rule.min_gpm)`,
     where `max_cv = clip(0.5 − 0.04 × min_gpm, 0.15, 0.5)`. Rejects
     spiky windows where a handful of high readings drag the mean up
     past threshold but the rest are zero — Flume sensor noise has a
     larger relative footprint at low GPM, so low-threshold rules
     (Leak at 0.1 GPM) get a tighter CV cap than high-threshold rules
     (Pipe Break at 8 GPM).

  Tradeoff: an *intermittent* leak (e.g. a joint that pulses) where most
  per-minute readings are zero will fail the CV gate and stay silent.
  This is a deliberate choice: we tried removing the CV gate on this
  branch (commits a672f9c → 652bb31 in PR #201) and a 7-day replay
  showed 6 Leak fires/week of ambiguous origin. Restored the gate;
  the proper fix for true intermittent leaks is to lower the per-rule
  `duration_minutes` so a shorter window can fully encompass each
  pulse, rather than weaken the noise rejection.
- **Cross-source suppression** — controller-active OR hose-timer-active state
  suppresses Flume `default_flow_rules` for `max_rule_duration + 10min`
  slack. Symmetric. HoseTimerProcessor writes `alert::__hose__::last_active`;
  AlertEngine reads it.
- **Stale-zone monitor** — separate `StaleZoneChecker` fires P-1 if any
  enabled controller zone or connected hose-timer valve hasn't run within
  `stale_zone_days` (default 7). Daily dedup per zone; hourly evaluation gate.
  Catches: schedule accidentally disabled, hose-timer hub offline, dead
  valve battery, etc.
- **Report failures escalate to Pushover** — weekly-email failure (e.g.
  Gmail auth error) fires P2 Pushover so you know immediately.

```bash
# Dry-run all rules against live Flume / Rachio (no Pushover sent)
uv run python RachioFlume/rfmanager.py alerts test

# Show per-rule state
uv run python RachioFlume/rfmanager.py alerts status

# Mute a rule (e.g. while doing plumbing work)
uv run python RachioFlume/rfmanager.py alerts mute "Pipe Break" --hours 4
uv run python RachioFlume/rfmanager.py alerts unmute "Pipe Break"
```

### 🔁 DB Replay — validate alerts against real data

Replay production `water_readings` + `watering_events` through the alert
engine without hitting Flume/Rachio APIs or sending Pushover. Useful for
verifying logic changes don't false-trigger on real data, and for tuning
predicates.

Two patterns:

```bash
# 1. Replay against the LOCAL DB (whatever's in your config path)
uv run python RachioFlume/rfmanager.py alerts replay --hours 168   # 7 days

# 2. Replay against a COPY of the prod DB (safest — no risk of writes to prod)
scp abutala@aibo:/home/abutala/logs/water_tracking.db /tmp/aibo_water_tracking.db
uv run python RachioFlume/rfmanager.py alerts replay \
    --hours 168 --db /tmp/aibo_water_tracking.db
```

Output is tab-aligned and shows the new label set: `REPORT` (P-1), `FIRE` (P2),
`CLEAR` (P0). Suppressed cycles are summarized at the bottom (the suppression
window includes both controller and hose-timer activity).

A clean 7-day replay against current prod data should produce ~24 `Zone Report`
entries (12 active zones × 2 cycles/week) and zero false `Pipe Break` / `Leak`
fires while irrigation is active.

### 🌐 Remote test loop on omega

Build locally, test remotely — without touching the running prod collector.

```bash
# From a feature branch on your local machine
./RachioFlume/scripts/remote-test.sh                                  # push + deploy + live dry-run + 24h replay
./RachioFlume/scripts/remote-test.sh --replay-hours 168                # replay 7 days instead of 24h
./RachioFlume/scripts/remote-test.sh --hot                             # restart prod collector after tests
```

One-time setup on omega (uses `~/Code-test` so prod `~/Code` is safe):
```bash
ssh omega "git clone https://github.com/DeviationLabs/homely-vibes ~/Code-test && cd ~/Code-test && uv sync --quiet"
ssh omega "ln -sf ~/Code/config/local.yaml ~/Code-test/config/local.yaml"
```

### 🧪 Synthetic Scenarios (unit tests only)

Hand-crafted scenarios (pipe break, slow leak, irrigation-overlap-leak, etc.)
live in [test_alert_simulation.py](test_alert_simulation.py) as pytest
assertions — built in-code via `SyntheticDataset.add_*` builders from
[synthetic_data.py](synthetic_data.py). No YAML, no separate CLI verb —
running `make test` exercises them.

The simulator's AlertEngine is constructed against the real merged config
(`default.yaml` + `local.yaml`), so a scenario run is also an integration
test of the config shape your production collector uses. See
[TESTABILITY.md](TESTABILITY.md) for the scenario taxonomy + assertions.

### 🛑 Stop Data Collection

```bash
# Find the background process
ps aux | grep "rfmanager.py collect"

# Stop it
kill <process_id>

# Or if running in foreground, just use Ctrl+C
```

### 🚀 Deployment runbook (aibo)

Production lives on `aibo`. The collector runs from cron's `@reboot` wrapped in
`run-one-constantly` (auto-restarts on exit), so deploying new code is a
3-step ritual.

Before any production deploy that changes the `rachio_flume.alerts` schema,
**migrate aibo's `local.yaml` first**. The new structured-config loader is
strict — an outdated schema crashes on startup.

```bash
# 1) Backup aibo's local.yaml (gitignored, host-specific)
ssh abutala@aibo 'cp ~/bin/Common-configs/Code_config_local.yaml \
    ~/bin/Common-configs/Code_config_local.yaml.bak-$(date +%Y%m%d-%H%M%S)'

# 2) Migrate the rachio_flume block to the new shape — easiest is:
#    a. scp it down, edit locally, scp back
#    b. or edit in place via ssh + python script
scp abutala@aibo:/home/abutala/bin/Common-configs/Code_config_local.yaml /tmp/aibo_local.yaml
# (edit /tmp/aibo_local.yaml to match new schema — keep host-specific blocks like node_check, prod_controller unchanged)
scp /tmp/aibo_local.yaml abutala@aibo:/home/abutala/bin/Common-configs/Code_config_local.yaml

# 3) Pull new code on aibo
ssh abutala@aibo 'cd ~/Code && git fetch origin && git pull origin main'

# 4) Verify new config loads cleanly before restart
ssh abutala@aibo 'cd ~/Code && uv run python -c "
from lib.config import reset_config, get_config; reset_config()
cfg = get_config()
print(\"zone_anomaly:\", cfg.rachio_flume.alerts.zone_anomaly.absolute_gpm)
print(\"flow rules:\", [r.name for r in cfg.rachio_flume.alerts.default_flow_rules])
print(\"stale days:\", cfg.rachio_flume.alerts.stale_zone_days)
"'

# 5) Kill the python collector process; run-one-constantly auto-restarts with new code
ssh abutala@aibo 'pkill -f ".venv/bin/python3 RachioFlume/rfmanager.py"'
sleep 12
ssh abutala@aibo 'ps auxf | grep ".venv/bin/python3 RachioFlume/rfmanager.py" | grep -v grep'

# 6) Tail logs to confirm a clean cycle
ssh abutala@aibo 'tail -25 ~/logs/rfmanager.py.log'
```

The first post-restart cycle should show: zones saved, Flume readings
saved, hose-timer valves listed (if any), and (if any zones are stale
beyond the threshold) the very first `Stale-zone alert sent: ...` message
— that's expected on new code or fresh DB.

## Architecture

### Components

1. **RachioClient** (`rachio_client.py`)
   - Interfaces with Rachio API
   - Retrieves zone information and watering events
   - Monitors active watering sessions

2. **FlumeClient** (`flume_client.py`)
   - Interfaces with Flume API using OAuth2 JWT authentication
   - Automatically discovers and queries all user devices
   - Aggregates water usage readings across multiple devices
   - Provides current flow rate data

3. **WaterTrackingDB** (`data_storage.py`)
   - SQLite database for persistent storage
   - Stores zones, events, readings, and computed sessions
   - Handles data relationships and indexing

4. **WaterTrackingCollector** (`collector.py`)
   - Orchestrates data collection from both APIs
   - Runs continuously or on-demand
   - Correlates watering events with usage data

5. **WeeklyReporter** (`reporter.py`)
   - Generates period reports with customizable date ranges (default 7 days)
   - Unified `ZoneStats` table covers controller zones and hose valves; hose entries sort after controllers via `HOSE_ZONE_SENTINEL=999`
   - Per-zone anomaly `threshold_gpm` and `alert_sessions` count surfaced alongside the aggregate stats
   - Supports HTML email delivery (via `<html><body><pre>` — auto-detected by `lib.Mailer`) and console output

6. **AlertEngine** (`alert_engine.py`) + **AlertRule** (`alert_rules.py`)
   - Runs at the end of each collector cycle
   - **Zone-end reporting**: detects when a Rachio zone finishes, waits for slack, sends one P-1 report per zone per day with runtime, avg GPM, total gallons
   - **Zone anomaly detection**: checks zone-end flow against per-zone thresholds (configured in `config/default.yaml` under `rachio_flume.alerts.zone_thresholds`). Alerts at P2 when flow exceeds `avg + max(0.5 GPM, 10% of avg)`. Unknown zones default to 0.5 GPM threshold.
   - **Anomaly rules**: evaluates each rule's predicate against trailing per-minute Flume readings — requires mean ≥ threshold AND CV ≤ max_cv (coefficient-of-variation filter rejects spiky noise)
   - Anomaly fires at P2 (emergency), at most once per day per rule; P0 clear on active→clear
   - Suppressed during (and just after) Rachio irrigation
   - Per-rule and per-zone reported-today state persisted as JSON in `collection_metadata`

7. **SyntheticDataset** (`synthetic_data.py`) + **Simulator** (`simulate_alerts.py`)
   - In-code scenarios (household, irrigation, leak, pipe-break) built via `SyntheticDataset.add_*` helpers
   - Plays back through `AlertEngine` with fake clients and a capturing Pushover
   - Used by `test_alert_simulation.py` for regression assertions
   - Ad-hoc replay of historical DB uses `rfmanager.py alerts replay` (see § DB Replay)

### Database Schema

- **zones**: Zone configuration and metadata
- **watering_events**: Raw events from Rachio API
- **water_readings**: Time-series usage data from Flume
- **zone_sessions**: Computed watering sessions with usage correlation

## API Rate Limits

- **Rachio**: 1,700 calls/day rate limit
- **Flume**: Check your plan's API limits

The collector is designed to respect these limits with configurable polling intervals.

## Example Output

### Period Report

Controllers and hose valves land in the same fixed-width table. `Thr` is the
per-zone anomaly threshold (blank when unconfigured); `Alrt` is the count of
sessions in the period whose per-session avg flow exceeded that threshold.
Emailed variant wraps this body in `<html><body><pre>` so iOS Mail / Gmail
render the whole table in monospace with no viewport wrap.

```
WATER USAGE REPORT
Period: 2026-06-26 to 2026-07-03
========================================

SUMMARY:
  Total watering sessions: 36
  Total duration: 465.0 min
  Total water used: 1828 gallons
  Zones watered: 13

ZONE DETAILS:
Name     Min    Gals  GPM   Thr   Alrt
--------------------------------------
Z1 FS    40.0   261   6.5   6.6   -
Z2 FS    39.7   211   5.3   6.0   -
...
Z12 FDB  59.5   82    1.4   1.5   -
Z13 FS   35.0   0     0.0   1.0   -
========================================
```

### Status Check
```
==================================================
WATER TRACKING SYSTEM STATUS
==================================================
Active Zone: #2 - Back Yard
Current Usage Rate: 0.85 GPM
Recent Sessions (24h): 3
Last Rachio Collection: 2023-07-15T10:30:00
Last Flume Collection: 2023-07-15T10:35:00
==================================================
```

## Testing

See [TESTABILITY.md](TESTABILITY.md) for the full testing strategy. Quick start:

```bash
# All RachioFlume tests
uv run python -m pytest RachioFlume/ -v

# Just alert engine unit tests (fastest)
uv run python -m pytest RachioFlume/test_alert_engine.py -v

# Synthetic scenario assertions
uv run python -m pytest RachioFlume/test_alert_simulation.py -v

# Zone threshold integration test (fetches DB from prod controller)
uv run python -m pytest RachioFlume/test_zone_thresholds.py -v
# Or standalone:
python RachioFlume/test_zone_thresholds.py

# Replay historical DB through the alert engine (no Pushover)
uv run python RachioFlume/rfmanager.py alerts replay --hours 168
```

### Zone Threshold Integration Test

The `test_zone_thresholds.py` integration test validates the zone anomaly detection logic against production data:

1. **Fetches the production database** from prod controller via SCP
2. **Loads zone thresholds** from config (12 zones with per-zone avg GPM)
3. **Tests threshold computation** for known/unknown zones
4. **Simulates zone-end scenarios** with real historical data
5. **Checks for threshold violations** in recent production sessions

**Threshold formula** (adaptive mode):
```
threshold = avg_gpm + max(absolute_gpm, percent_above/100 × avg_gpm)
```

Actual baselines live in `config/local.yaml` under
`rachio_flume.alerts.zone_anomaly.zone_thresholds` — see the file for
current per-zone `avg_gpm` values and their tuning notes. **Unknown zones**
(not in config) default to `avg_gpm=0`, yielding a 0.5 GPM threshold — any
flow triggers an alert.

**Config key convention**: Controllers key by stringified `zone_number`
(`"1"`, `"2"`, …) because that's what the Rachio API surfaces per run.
Hose valves key by their raw API name (e.g. `"Z13 FS - Upper Deck Planters"`)
for the same reason — the hose API has no zone number. Display strings for
both come from `compact_zone_label()` (splits on `" - "` and takes the head),
so `"Z13 FS - Upper Deck Planters"` shows as `"Z13 FS"` in the email and
Pushover header. No separate `name:` field in config.

**Requirements**: SSH access to prod controller (configured in `config/local.yaml`) must work without password prompt (key-based auth).

## Development

The integration follows the existing project patterns:
- Uses pydantic for data models
- Implements proper error handling
- Includes comprehensive logging
- Supports async operations where beneficial
- Maintains clean separation of concerns