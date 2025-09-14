# August Smart Lock Monitor

Monitor August Smart Locks and send notifications when locks remain unlocked longer than expected.

## Setup

Install August API library:
```bash
uv add yalexs
```

Add credentials to `lib/Constants.py`:
```python
AUGUST_EMAIL = "your_august_email@example.com"
AUGUST_PASSWORD = "your_august_password"
AUGUST_PHONE = "+1234567890"  # Required for 2FA
```

**Important**: Use your actual August account credentials. The phone number is required for 2FA verification.

**2FA Setup**: August accounts typically require 2FA. If authentication fails:
1. Open the August app on your phone
2. Complete any pending 2FA verification
3. Try the authentication test again

## Usage

Continuous monitoring (check every 60s, alert after 5min):
```bash
uv run python August/august_manager.py monitor --continuous
```

Custom intervals:
```bash
uv run python August/august_manager.py monitor --continuous --interval 30 --threshold 3
```

Status check:
```bash
uv run python August/august_manager.py status
```

Test commands:
```bash
uv run python August/august_manager.py test --auth
uv run python August/august_manager.py test --notification
```

## How It Works

1. Polls lock status at intervals (default: 60s)
2. Tracks when locks become unlocked
3. Sends pushover alerts if unlocked beyond threshold (default: 5min)
4. 30-minute cooldown prevents notification spam
5. State persists across restarts

## Testing

```bash
uv run python -m pytest August/test_august.py -v
```