# NetworkCheck

Network uplink monitoring — speed tests and external IP tracking for the home network ("Eden"). Reports via email and Pushover.

## Components

### `test_uplink.py` — Speed test

Runs `speedtest-cli` and classifies the link:

| Status | Condition |
|--------|-----------|
| **Good** | DL ≥ `min_dl_bw` AND UL ≥ `min_ul_bw` |
| **Degraded** | DL ≥ 80% threshold AND UL ≥ 80% threshold |
| **Bad** | Below 80% of either threshold |

Supports `--max_retries N` (waits 60s between attempts) and `--always_email` to force email delivery.

Thresholds configured in `config/default.yaml` → `network_check`:
```yaml
network_check:
  min_dl_bw: 150  # Mbps
  min_ul_bw: 4    # Mbps
```

### `external_ip_reporter.py` — IP change monitor

Fetches the current external IP from a cascade of services (ipify → icanhazip → checkip) and reports via email + Pushover. Useful for detecting dynamic IP changes.

## Notifications

Both scripts use:
- **Email** via `lib.Mailer`
- **Pushover** via the `NetworkCheck` app token (`config/local.yaml` → `pushover.tokens.NetworkCheck`)

## Usage

```bash
# Speed test (single attempt)
uv run python -m NetworkCheck.test_uplink

# Speed test with 3 retries
uv run python -m NetworkCheck.test_uplink --max_retries 3

# Speed test with email
uv run python -m NetworkCheck.test_uplink --always_email

# External IP report
uv run python -m NetworkCheck.external_ip_reporter
```
