# August Smart Lock Monitor

Monitor August Smart Locks with comprehensive alerting for unlock duration, door ajar detection, lock failures, and low battery warnings.

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

Continuous monitoring (default check every 60s, alert after 5min):
```bash
uv run python August/august_manager.py monitor
```

Custom thresholds and intervals:
```bash
uv run python August/august_manager.py monitor \
  --poll-secs 30 \
  --lock-mins 3 \
  --ajar-mins 15 \
  --battery-pct 15
```

Test commands:
```bash
uv run python August/august_manager.py test --auth          # Test authentication
uv run python August/august_manager.py test --notification  # Test notifications
uv run python August/validate_2fa.py 123456                 # Complete 2FA with code
```

## Alert Types

🔓 **Unlock Alerts**: Lock remains unlocked longer than threshold (default: 5min)  
🚪 **Door Ajar Alerts**: Door stays open longer than threshold (default: 10min)  
🔐 **Lock Failure Alerts**: Door closed but failed to lock automatically  
🔋 **Low Battery Alerts**: Battery below threshold (default: 20%)  

## Alert Frequencies

- **Lock/Door alerts**: Maximum once every 10 minutes per lock
- **Battery alerts**: Maximum once every 24 hours per lock  
- **State persistence**: All tracking survives application restarts

## Testing

```bash
uv run python -m pytest August/test_august.py -v
```