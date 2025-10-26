# NodeCheck - Device Monitoring and Management

NodeCheck provides monitoring and management for Foscam cameras, Windows machines, and generic IoT devices.

## Architecture

- **`manage_nodes.py`** - Device management, health checks, and reboots
- **`heartbeat_nodes.py`** - Continuous monitoring with smart notifications
- **`nodes.py`** - Shared Node class hierarchy

## Quick Start

### Continuous Monitoring

```bash
uv run NodeCheck/heartbeat_nodes.py --poll 3600 --cooloff 600
uv run NodeCheck/heartbeat_nodes.py --poll 300 --cooloff 300 --nodes "omega" --nodes "flume"
uv run NodeCheck/heartbeat_nodes.py --poll 60 --cooloff 60 --nodes "fake" --debug
```

### Device Management

```bash
uv run NodeCheck/manage_nodes.py --type foscam
uv run NodeCheck/manage_nodes.py --type windows --reboot
uv run NodeCheck/manage_nodes.py --type foscam --always_email
```

## Features

### Continuous Monitoring (`heartbeat_nodes.py`)

- Multi-device support for foscam, windows, and generic devices
- Pushover alerts with configurable cooloff periods  
- Case-insensitive filtering
- Uniform ping-based health checks
- Recovery detection notifications

### Device Management (`manage_nodes.py`)

- Type-specific operations per device type
- Comprehensive health verification
- Automated reboots with verification
- Email reporting
- Real-time Pushover notifications

### Node Classes (`nodes.py`)

- **`Node`**: Abstract base class
- **`FoscamNode`**: Camera operations (image capture, HTTP reboot)
- **`WindowsNode`**: SSH commands, uptime checks
- **`GenericNode`**: Ping-only monitoring

## Configuration

```python
NODE_CONFIGS = {
    "Deck Stairs": NodeConfig("192.168.1.51", "foscam", FOSCAM_USERNAME, FOSCAM_PASSWORD),
    "Beta": NodeConfig("192.168.1.100", "windows", WINDOWS_USERNAME, WINDOWS_PASSWORD),
    "Omega": NodeConfig("192.168.1.101", "generic"),
}
```

## Command Reference

### Heartbeat Monitor Options

| Option | Description | Default |
|--------|-------------|---------|
| `--poll` | Polling interval in seconds | 3600 (1 hour) |
| `--cooloff` | Notification cooloff in seconds | 3600 (1 hour) |
| `--nodes` | Specific devices to monitor | All devices |
| `--debug` | Enable debug logging | False |

### Node Manager Options

| Option | Description | Default |
|--------|-------------|---------|
| `--type` | Device type (foscam/windows) | foscam |
| `--reboot` | Perform reboots after checks | False |
| `--always_email` | Send email report regardless | False |
| `--debug` | Enable debug logging | False |

## Notifications

### Pushover Integration

- Priority 1 alerts for device failures
- Smart cooloff prevents notification spam  
- Recovery notifications when devices return online
- Batch notifications for multiple device failures

### Email Reports

- Device status summary
- Error details and timestamps
- Reboot operation results  
- Overall system health assessment

## Examples

### Basic Monitoring Setup

```bash
uv run NodeCheck/heartbeat_nodes.py \
  --poll 600 --cooloff 1800 \
  --nodes "Deck Stairs" --nodes "Beta" --nodes "Omega"
```

### Weekly Maintenance  

```bash
uv run NodeCheck/manage_nodes.py --type foscam --reboot --always_email
uv run NodeCheck/manage_nodes.py --type windows --reboot --always_email
```

### Troubleshooting

```bash
uv run NodeCheck/heartbeat_nodes.py \
  --poll 30 --cooloff 60 --nodes "problematic_device" --debug
```

## Integration

NodeCheck integrates with the broader home automation system:

- **Shared configuration** via `lib/Constants.py`
- **Common utilities** from `lib/` (networking, notifications, logging)
- **Coordinated monitoring** with other system components
- **Centralized alerting** through Pushover and email

The modular design allows NodeCheck to operate independently while sharing resources with other automation components.