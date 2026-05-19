# Rachio-Flume Water Tracking Integration

A Python integration that connects Rachio irrigation controllers with Flume water monitoring devices to track zone-specific water usage and generate comprehensive reports.

## Features

- **Rachio Integration**: Monitor active zones and watering events
- **Flume Integration**: Track real-time water consumption across all devices
- **Data Correlation**: Match watering events with water usage patterns
- **Usage Alerts** (`alert_engine.py`): First-party Pushover alerts for Pipe Break / High Flow / Mid Flow / Low Flow / Leak, suppressed during Rachio irrigation, with mute support and "all clear" notifications
- **Synthetic Simulator** (`simulate_alerts.py`): Replay a YAML-defined scenario through the alert engine without hitting real APIs or Pushover — see [TESTABILITY.md](TESTABILITY.md)
- **Period Reports**: Generate detailed reports with:
  - Average watering rate by zone
  - Total duration each zone was watered
  - Water efficiency analysis
- **Continuous Monitoring**: Automated data collection service
- **SQLite Storage**: Persistent data storage with session tracking

## Setup

### Credentials Configuration

Add your API credentials to `config/local.yaml`:

```yaml
# Rachio API credentials
rachio:
  api_key: abc123...
  rachio_id: device-uuid...

# Flume API credentials (get from https://portal.flumetech.com/#token)
flume:
  client_id: client-id...
  client_secret: client-secret...
  user_email: your-email@example.com
  password: your-password...
```

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

**💡 Pro Tip**: Let the collector run for at least a week to get meaningful reports and efficiency analysis!

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

# Send report via email
uv run python rfmanager.py report --email

# Zone efficiency analysis (requires multiple watering sessions)
uv run python rfmanager.py summary

# Raw data report with 5-minute intervals
uv run python rfmanager.py raw --hours 48
```

### 🚨 Usage Alerts

The collector evaluates configurable flow-rate alerts each polling cycle. Defaults
mirror the Flume app screenshots (Pipe Break, High Flow, Mid Flow, Low Flow, Leak)
and live in `config/default.yaml` under `rachio_flume.alerts` — override per-house
in `config/local.yaml`.

Key behaviors:
- **All alerts at Pushover priority 2** (emergency — retries until you ack)
- **Re-trigger every 30 min** while the condition holds, unless muted
- **Priority-0 "all clear" notification** on the cycle the condition transitions active → clear
- **Suppression while Rachio irrigates** (plus a 10-min slack after the zone completes, to cover the trailing flow window in the predicate's lookback)

```bash
# Dry-run all rules against live Flume / Rachio (no Pushover sent)
uv run python -m RachioFlume.rfmanager alerts test

# Show per-rule state
uv run python -m RachioFlume.rfmanager alerts status

# Mute a rule (e.g. while doing plumbing work)
uv run python -m RachioFlume.rfmanager alerts mute "Pipe Break" --hours 4
uv run python -m RachioFlume.rfmanager alerts unmute "Pipe Break"
```

### 🧪 Synthetic Simulator

Replay a hand-crafted scenario through the engine — no real APIs, no Pushover,
events printed to stdout. Useful for tuning rules or validating changes.

```bash
# Default scenario at config/synthetic_alerts.yaml
uv run python -m RachioFlume.rfmanager simulate

# Custom scenario file + poll cadence
uv run python -m RachioFlume.rfmanager simulate --config my_scenario.yaml --poll-interval 5
```

See [TESTABILITY.md](TESTABILITY.md) for the scenario schema and worked examples.

### 🛑 Stop Data Collection

```bash
# Find the background process
ps aux | grep "rfmanager.py collect"

# Stop it
kill <process_id>

# Or if running in foreground, just use Ctrl+C
```

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
   - Generates period-based reports with customizable date ranges
   - Calculates zone efficiency metrics
   - Supports email delivery and console output

6. **AlertEngine** (`alert_engine.py`) + **AlertRule** (`alert_rules.py`)
   - Runs at the end of each collector cycle
   - Evaluates each rule's predicate against trailing per-minute Flume readings
   - State machine: first-fire / retrigger / clear / muted
   - Suppresses during (and just after) Rachio irrigation
   - Per-rule state persisted as JSON in the existing `collection_metadata` table

7. **SyntheticDataset** (`synthetic_data.py`) + **Simulator** (`simulate_alerts.py`)
   - YAML-defined scenarios with household, irrigation, leak, and pipe-break events
   - Plays back through `AlertEngine` with fake clients and a capturing Pushover
   - Used by `test_alert_simulation.py` for regression assertions and by the
     `simulate` CLI for ad-hoc tuning

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
```
======================================================================
WATER USAGE REPORT
Period: 2023-07-10 to 2023-07-17
======================================================================

SUMMARY:
  Total watering sessions: 12
  Total duration: 8.5 hours
  Total water used: 425.3 gallons
  Zones watered: 4

ZONE DETAILS:
Zone Name                Sessions Duration(h) Water(gal) Rate(gpm)
--------------------------------------------------------------------
1    Front Lawn          4        2.5         127.5      0.85
2    Back Yard           3        2.0         98.2       0.82
3    Side Garden         3        1.8         89.1       0.83
4    Vegetable Garden    2        2.2         110.5      0.84
======================================================================
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

# Visual playback of a scenario (events to screen, no Pushover)
uv run python -m RachioFlume.rfmanager simulate
```

## Development

The integration follows the existing project patterns:
- Uses pydantic for data models
- Implements proper error handling
- Includes comprehensive logging
- Supports async operations where beneficial
- Maintains clean separation of concerns