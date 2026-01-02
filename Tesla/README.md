# Tesla Powerwall Management System

A Python system for managing Tesla Powerwall operations with automated power management decisions based on battery levels, time windows, and configurable thresholds.

## Features

- **Automated Power Management**: Make intelligent decisions about backup reserve and storm watch modes
- **Battery History Tracking**: Monitor battery percentage trends and calculate gradients
- **Configurable Decision Points**: Set time-based rules for different power management strategies
- **Notification System**: Pushover notifications for important events and changes
- **Trail Stop Protection**: Implement trailing stop logic for battery management
- **Comprehensive Logging**: Detailed logging of all operations and decisions

## Setup

From the project root directory:

```bash
make setup
```

This will:

- Install project dependencies with `uv sync`
- Set up pre-commit hooks
- Configure the development environment

### Environment Configuration

1. Copy the Constants template:

   ```bash
   cp lib/Constants.py.sample lib/Constants.py
   ```

2. Edit `lib/Constants.py` and configure:

   - Tesla API credentials
   - Pushover notification settings (if using notifications)
   - Email settings (if using email notifications)
   - Logging directories

### Tesla Authentication

The system uses custom OAuth2 + PKCE for Tesla API access. You'll need to authenticate once.

**Recommended: Manual Authentication** (Tesla uses hCaptcha):

```bash
uv run python Tesla/tesla_auth_manual.py
```

This will print an auth URL. Open it in your regular browser, complete login + hCaptcha, then paste the callback URL back. Text-only, no display required on server.

**Alternative: Semi-Automated** (requires display):

```bash
uv run python Tesla/tesla_auth.py
```

Opens Chrome via Selenium, attempts automation, falls back to manual if hCaptcha appears. Requires display/X11.

**Token Storage**: Tokens saved to `~/logs/tesla_tokens.json` with 0o600 permissions. Auto-refresh without browser after initial auth.

## Usage

Run commands from the project root directory:

### Basic Power Management

```bash
# Run power management with default settings
uv run python Tesla/manage_power.py --send-notifications --quiet


### Configuration Options

```bash
# Show all available options
uv run python Tesla/manage_power.py --help
```

Key options:

- `--send-notifications`: Enable Pushover notifications
- `--debug`: Enable debug logging
- `--quiet`: Suppress console output (logs still written to file)
- `--email`: Specify Tesla account email (defaults to Constants.POWERWALL_EMAIL)

## Architecture

### Core Components

1. **PowerwallManager** (`manage_power.py`)
   - Main orchestrator for power management decisions
   - Handles Tesla API communication
   - Manages decision point evaluation

2. **BatteryHistory** (`manage_power.py`)
   - Tracks battery percentage over time
   - Calculates gradients and trends
   - Supports extrapolation for future predictions

3. **DecisionPoint** (`manage_power.py`)
   - Configurable rules for power management
   - Time-based thresholds and actions
   - Support for conditional logic and trailing stops

### Decision Logic

The system evaluates decision points based on:

- Current time windows
- Battery percentage thresholds
- Battery gradient (charging/discharging rate)
- Historical trends
- Trailing stop conditions

## Configuration

### Decision Points

Decision points are configured in the code and define when to change power modes:

```python
DecisionPoint(
    time_start=800,  # 8:00 AM
    time_end=1200,   # 12:00 PM
    pct_thresh=85.0, # Battery threshold
    pct_gradient_per_hr=5.0, # Required charging rate
    iff_higher=True, # Trigger if battery is higher
    op_mode="backup", # Target operation mode
    pct_min=80.0,    # Minimum battery level
    reason="Morning solar charging"
)
```

### Operation Modes

- `backup`: Backup-only mode (normal operation)
- `self_consumption`: Self-consumption mode
- `autonomous`: Autonomous operation
- `storm_watch`: Storm watch mode (maximum reserve)

## Testing

```bash
# Run all tests
uv run python -m pytest Tesla/test_manage_power.py -v
```

## Troubleshooting

### Authentication Issues

If you see "Tesla token expired" errors, re-authenticate:

```bash
# Recommended - text-only
uv run python Tesla/tesla_auth_manual.py

# Or with display
uv run python Tesla/tesla_auth.py
```

### Chrome/Display Issues

**Manual auth** (`tesla_auth_manual.py`): No display required - authenticate in any browser on any machine.

**Selenium auth** (`tesla_auth.py`): Requires Chrome and display (X11/VNC). Use manual auth for headless servers.
