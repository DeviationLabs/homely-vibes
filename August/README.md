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

**2FA Setup**: August accounts require 2FA for security. The system handles this automatically:
1. Run authentication test: `uv run python August/august_manager.py test --auth`
2. If 2FA is needed, verification code will be sent to your phone/email
3. Use the validation script: `uv run python August/validate_2fa.py YOUR_CODE`
4. Once successful, tokens are cached for ~7 days (no more 2FA needed)

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
uv run python August/august_manager.py test --auth          # Test authentication
uv run python August/august_manager.py test --notification  # Test notifications
uv run python August/validate_2fa.py 123456                 # Complete 2FA with code
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