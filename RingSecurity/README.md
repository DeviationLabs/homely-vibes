# RingSecurity

Daily health check for Ring devices (doorbells, cameras, chimes).

- **P1 alert** — any device battery below `battery_threshold_pct` (default 25%)
- **P0 alert** — any device offline / unreachable
- **P0 alert** — Ring auth rejected / re-auth needed
- **P1 alert** — Ring check failed (unexpected error)

One-shot invocation designed for a daily cron. No polling loop, no state file.

## Setup

1. Add credentials to `config/local.yaml`:
   ```yaml
   ring:
     username: your@email.com
     password: your_password
   pushover:
     tokens:
       Ring Security: <your-pushover-app-token>
   ```

2. First-time 2FA login (writes token to `config/tokens/ring_auth_token.json`):
   ```bash
   uv run python RingSecurity/ring_manager.py auth
   ```
   Enter the code Ring sends via SMS/email when prompted.

## Daily run

```bash
uv run python RingSecurity/ring_manager.py check 2>&1 | tee /tmp/ring_check.log
```

Schedule via cron/launchd once per day. Exit code is non-zero on auth failure or generic Ring-check failure (which push P0 and P1 alerts respectively).

## Tests

```bash
uv run python -m pytest RingSecurity -v
```
