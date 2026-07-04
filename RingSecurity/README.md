# RingSecurity

Daily health check for Ring devices (doorbells, cameras, chimes).

- **P1 alert** — any device battery below `battery_threshold_pct` (default 25%)
- **P2 alert** — any device offline / unreachable

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

Schedule via cron/launchd once per day. Exit code is non-zero only on Ring-check failure (which itself pushes a P1 alert).

## Tests

```bash
uv run python -m pytest RingSecurity -v
```
