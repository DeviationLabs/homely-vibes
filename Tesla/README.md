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
- Initialize Git submodules (including TeslaPy)
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

The system uses TeslaPy for Tesla API access. You'll need to authenticate once:

```bash
# Run TeslaPy GUI for initial authentication
cd ext_lib/TeslaPy
python gui.py
```

This will open a browser window for Tesla OAuth authentication. Follow the prompts to authorize the application.

## Usage

All commands should be run from the Tesla directory:

### Basic Power Management

```bash
# Run power management with default settings
uv run python manage_power_clean.py

# Run with specific battery threshold
uv run python manage_power_clean.py --battery-threshold 80

# Enable notifications
uv run python manage_power_clean.py --notify

# Dry run mode (no actual changes)
uv run python manage_power_clean.py --dry-run
```

### Configuration Options

```bash
# Show all available options
uv run python manage_power_clean.py --help
```

Key options:

- `--battery-threshold`: Set minimum battery percentage (default: 75)
- `--notify`: Enable Pushover notifications
- `--dry-run`: Test mode without making actual changes
- `--verbose`: Enable detailed logging

## Architecture

### Core Components

1. **PowerwallManager** (`manage_power_clean.py`)
   - Main orchestrator for power management decisions
   - Handles Tesla API communication
   - Manages decision point evaluation

2. **BatteryHistory** (`manage_power_clean.py`)
   - Tracks battery percentage over time
   - Calculates gradients and trends
   - Supports extrapolation for future predictions

3. **DecisionPoint** (`manage_power_clean.py`)
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
uv run python -m pytest test_manage_power_clean.py -v

# Run specific test classes
uv run python -m pytest test_manage_power_clean.py::TestBatteryHistory -v
```

## Troubleshooting

### Authentication Issues

If you see "Tesla token expired" errors:

```bash
cd ../ext_lib/TeslaPy
python gui.py
```

This will refresh your Tesla authentication token.

### TeslaPy Not Found

Ensure the ext_lib directory is properly created and TeslaPy is cloned:

```bash
ls -la ext_lib/TeslaPy/
```

You should see the TeslaPy files including `teslapy.py`.

### Constants Configuration

Make sure `lib/Constants.py` exists and is properly configured with your credentials and settings.

## Development

The system follows the existing project patterns:

- Uses dataclasses for structured data
- Implements comprehensive error handling
- Includes detailed logging throughout
- Supports both production and testing modes
- Maintains clean separation of concerns
