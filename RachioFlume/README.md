# Rachio-Flume Water Tracking Integration

A Python integration that connects Rachio irrigation controllers with Flume water monitoring devices to track zone-specific water usage and generate comprehensive reports.

## Features

- **Rachio Integration**: Monitor active zones and watering events
- **Flume Integration**: Track real-time water consumption across all devices 
- **Data Correlation**: Match watering events with water usage patterns
- **Weekly Reports**: Generate detailed reports with:
  - Average watering rate by zone
  - Total duration each zone was watered
  - Water efficiency analysis
- **Continuous Monitoring**: Automated data collection service
- **SQLite Storage**: Persistent data storage with session tracking

## Setup

### Environment Variables

Create a `.env` file or set these environment variables:

```bash
# Rachio API credentials
RACHIO_API_KEY=your_rachio_api_key
RACHIO_ID=your_rachio_device_id

# Flume API credentials (get from https://portal.flumetech.com/#token)
FLUME_CLIENT_ID=your_flume_client_id
FLUME_CLIENT_SECRET=your_flume_client_secret
FLUME_USERNAME=your_flume_username
FLUME_PASSWORD=your_flume_password
```

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Or using poetry (if available in parent project)
poetry install
```

## Usage

### Data Collection

```bash
# Run single data collection cycle
python main.py collect --once

# Run continuous collection (every 5 minutes)
python main.py collect --continuous

# Run continuous with custom interval (every 10 minutes)
python main.py collect --continuous --interval 600
```

### System Status

```bash
# Check current system status
python main.py status
```

### Reports

```bash
# Generate current week report
python main.py report --current-week

# Generate last week report  
python main.py report --last-week

# Save report to JSON file
python main.py report --current-week --save

# Zone efficiency analysis
python main.py report --efficiency
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
   - Generates comprehensive reports
   - Calculates zone efficiency metrics
   - Exports data in multiple formats

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

### Weekly Report
```
=============================================================
WEEKLY WATER USAGE REPORT
Week: 2023-07-10 to 2023-07-17
=============================================================

SUMMARY:
  Total watering sessions: 12
  Total duration: 8.5 hours
  Total water used: 425.3 gallons
  Zones watered: 4

ZONE DETAILS:
Zone Name                Sessions Duration(h) Water(gal) Avg Rate(gpm)
----------------------------------------------------------------------
1    Front Lawn          4        2.5         127.5       0.85    
2    Back Yard           3        2.0         98.2        0.82
3    Side Garden         3        1.8         89.1        0.83  
4    Vegetable Garden    2        2.2         110.5       0.84
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

```bash
# Run all tests
python -m pytest test_integration.py -v

# Run specific test class
python -m pytest test_integration.py::TestRachioClient -v
```

## Development

The integration follows the existing project patterns:
- Uses pydantic for data models
- Implements proper error handling
- Includes comprehensive logging
- Supports async operations where beneficial
- Maintains clean separation of concerns