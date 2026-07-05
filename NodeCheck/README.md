# NodeCheck - Device Monitoring and Management

NodeCheck provides monitoring and management for Foscam cameras, Windows machines, and generic IoT devices.

## Architecture

- **`manage_nodes.py`** - Device management, health checks, and reboots
- **`heartbeat_nodes.py`** - Continuous monitoring with smart notifications
- **`nodes.py`** - Shared Node class hierarchy
- **`check_hw_specs.py`** - Remote hardware specs gatherer (SSH into a Linux/Pi host)

## Quick Start

### Continuous Monitoring

```bash
uv run NodeCheck/heartbeat_nodes.py --poll 3600 --cooloff 600
uv run NodeCheck/heartbeat_nodes.py --poll 300 --cooloff 300 --nodes "Server1" --nodes "WinBox1"
uv run NodeCheck/heartbeat_nodes.py --poll 60 --cooloff 60 --nodes "fake" --debug
```

### Device Management

```bash
uv run NodeCheck/manage_nodes.py --type foscam
uv run NodeCheck/manage_nodes.py --type windows --reboot
uv run NodeCheck/manage_nodes.py --type foscam --always_email
```

### Hardware Specs

```bash
uv run NodeCheck/check_hw_specs.py --ip 192.168.1.200
uv run NodeCheck/check_hw_specs.py --ip 192.168.1.200 --user <ssh-user> --port 22
```

SSHes into the host and prints model, SoC, CPU, memory, storage, network
(ethernet link speed via `ethtool`), PCI/USB buses, OS, firmware, and
temperature. Prompts for a sudo password only if the remote requires one
(tries passwordless first).

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

Add to `config/local.yaml`:

```yaml
node_check:
  foscam:
    username: your_username
    password: your_password
  windows:
    username: your_username
    password: your_password
  node_configs:
    "Camera1":
      ip: "192.168.1.51"
      node_type: foscam
      username: your_username
      password: your_password
    "WinBox1":
      ip: "192.168.1.100"
      node_type: windows
      username: your_username
      password: your_password
    "Server1":
      ip: "192.168.1.101"
      node_type: generic
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
  --nodes "Camera1" --nodes "WinBox1" --nodes "Server1"
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

- **Shared configuration** via `config/local.yaml`
- **Common utilities** from `lib/` (networking, notifications, logging)
- **Coordinated monitoring** with other system components
- **Centralized alerting** through Pushover and email

The modular design allows NodeCheck to operate independently while sharing resources with other automation components.