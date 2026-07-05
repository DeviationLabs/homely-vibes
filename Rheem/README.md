# Rheem EcoNet Water Heater Monitor

Monitor Rheem/EcoNet-connected water heaters and alert when available hot water is low, clearing the alert when it recovers to mid.

## How it works

The tank reports hot water availability as discrete levels via the unofficial EcoNet (ClearBlade) API:

| Level | Meaning          | Action                          |
|-------|------------------|---------------------------------|
| 0     | empty            | 🚨 fire **P2** alert (emergency) |
| 33    | "1/3rd full"     | 🔴 fire **P1** alert             |
| 66    | "2/3rd full"     | 🟢 send **P-1** clear, reset     |
| 100   | full             | no-op (already cleared at 66)   |
| None  | not supported    | skip silently                    |

Hysteresis with persisted state (`{logging_dir}/rheem_monitor_state.json`) prevents re-alerting every poll and flapping between adjacent levels. State is keyed by heater serial number, so multiple heaters are tracked independently. A tank that drops from 1/3rd (P1) to empty (P2) **escalates** — a second, higher-priority alert fires. Recovering from empty back to 1/3rd does NOT re-alert (still in the low zone); only recovery to ≥ mid clears the alert.

## Setup

```bash
uv sync   # installs pyeconet (unofficial EcoNet client)
```

Add credentials to `config/local.yaml`:

```yaml
rheem:
  email: your_econet_email@example.com
  password: your_econet_password
  poll_seconds: 300          # check interval (monitor command)
  empty_threshold: 0         # <= this -> P2 emergency (retries until acked)
  low_threshold: 33          # <= this -> P1 high (bypasses quiet hours)
  mid_threshold: 66          # >= this -> P-1 clear, reset alert state
```

Add a Pushover app token:

```yaml
pushover:
  tokens:
    Rheem: your_pushover_app_token
```

> **Auth**: EcoNet uses plain email/password → bearer `user_token`. No 2FA.

## Usage

```bash
# One-shot status check + Pushover summary
uv run python Rheem/rheem_manager.py test

# Continuous monitoring (interval from config)
uv run python Rheem/rheem_manager.py monitor

# Custom poll interval
uv run python Rheem/rheem_manager.py monitor --poll-secs 120
```

## Alert priorities

Per the repo convention (`P{N}` = Pushover `priority=N`):

- **P2** — empty tank (emergency, retries until acked). Seconds matter — no hot water at all.
- **P1** — low hot water (1/3rd full). Actionable within hours.
- **P-1** — recovery clear (silent, informational).
- **P0** — auth/comms failure (a chore, not an emergency).

## Caveats

- **Unofficial API.** `pyeconet` reverse-engineers Rheem's ClearBlade cloud (`rheem.clearblade.com`). Rheem can change endpoints without notice; the library could break at any time.
- **Discrete levels only.** The tank exposes 0/33/66/100, not a continuous percentage. Thresholds must align to these levels (defaults: low=33, mid=66).
- **Some tanks don't report `@HOTWATER`.** Availability is `None`; the monitor skips them with a debug log. No alert is fired for unsupported tanks.

## Testing

```bash
uv run python -m pytest Rheem/ -v
```

Tests use injected fakes (fake EcoNet api, fake notifier) — no `patch()`, per repo convention.
