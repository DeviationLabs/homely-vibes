# Tesla Powerwall Management System

A Python system for managing Tesla Powerwall operations via the **Tesla Fleet API**, with automated power-management decisions based on battery level, time windows, and configurable thresholds.

> **2026-06 migration note:** Tesla deprecated the Owner API (`owner-api.teslamotors.com`) for energy products. This module now uses the **Fleet API** via the `tesla-fleet-api` Python SDK and a registered third-party developer app. See [Initial Fleet API Setup](#initial-fleet-api-setup) for the one-time onboarding.

## Features

- **Automated Power Management**: Intelligent decisions about backup reserve and operation mode
- **Battery History Tracking**: Monitor battery percentage trends and calculate gradients
- **Configurable Decision Points**: Time-based rules in `config/default.yaml` under `tesla.decision_points`
- **Pushover Notifications**: Alerts on mode/reserve changes
- **Trail Stop Protection**: Trailing-stop logic for reserve management
- **Comprehensive Logging**: Detailed logs under the configured `paths.logging_dir`

## Day-to-day Usage

Run from the project root.

```bash
# Run the monitoring loop (long-running)
uv run Tesla/manage_power.py --send-notifications --quiet

# Re-mint tokens if expired (refresh tokens last 90+ days; access tokens ~8 hr auto-refresh)
uv run Tesla/tesla_auth.py
```

Key flags:

- `--send-notifications` — enable Pushover alerts
- `--debug` — verbose logging
- `--quiet` — suppress stdout (file logs remain)
- `--email` — override `tesla.powerwall_email`

Tests:

```bash
uv run python -m pytest Tesla/ -v
```

---

## Initial Fleet API Setup

This is a **one-time** setup. Once complete, day-to-day usage doesn't need any of these steps. Expect ~2 hours, mostly Tesla portal clickops + DNS, not code.

### Prerequisites

- A Tesla account that owns the Powerwall (with MFA enabled).
- An HTTPS-reachable domain you control — used to host your app's public key. This repo uses `deviationlabs.com` via GitHub Pages.
- Pushover account (for alerts) and the rest of `config/local.yaml` already populated.

### Step 1: Generate keypair

```bash
openssl ecparam -name prime256v1 -genkey -noout -out lib/tokens/tesla_fleet_private.pem
openssl ec -in lib/tokens/tesla_fleet_private.pem -pubout -out lib/tokens/tesla_fleet_public.pem
chmod 600 lib/tokens/tesla_fleet_private.pem
```

`lib/tokens/` is gitignored, so the private key never leaves your machine.

### Step 2: Host the public key

Tesla validates the public key at this exact path:

```
https://<your-domain>/.well-known/appspecific/com.tesla.3p.public-key.pem
```

For GitHub Pages (this repo's choice):

1. Add the contents of `lib/tokens/tesla_fleet_public.pem` to your Pages repo at `.well-known/appspecific/com.tesla.3p.public-key.pem`.
2. Add an empty `.nojekyll` file at the repo root (Jekyll otherwise strips `.`-prefixed directories).
3. Wait ~30s for the Pages deploy, then verify:

```bash
curl -I https://<your-domain>/.well-known/appspecific/com.tesla.3p.public-key.pem
# expect: HTTP 200
```

### Step 3: Register a Tesla developer app

At [developer.tesla.com](https://developer.tesla.com), create a Fleet API Application:

| Field | Value |
|---|---|
| App Name | `homely-vibes-powerwall` |
| Description | Personal Powerwall monitoring and intelligent reserve management |
| Purpose of Usage | Self-use automation for my own Tesla Powerwall — polling live status and adjusting backup reserve / operation mode based on time-of-use schedule |
| Open Source Contribution | No |
| OAuth Grant Type | **Authorization Code and Machine-to-Machine** (must be this — not Machine-to-Machine only) |
| Allowed Scopes | ✅ Profile Information ✅ Energy Product Information ✅ Energy Product Commands (uncheck all vehicle scopes) |
| Allowed Origin(s) | `https://<your-domain>` |
| Allowed Redirect URI(s) | `http://localhost:8585/callback` |
| Allowed Returned URL(s) | `http://localhost:8585/callback` |
| Application Domain | `<your-domain>` (must match Step 2's host) |
| Billing Details | Skip (personal $10/mo credit covers energy reads) |

After approval, capture **Client ID** and **Client Secret**.

### Step 4: Configure `config/local.yaml`

Add the Fleet API credentials under `tesla:`:

```yaml
tesla:
  # ... existing keys ...
  fleet_client_id: "<your-client-id>"
  fleet_client_secret: '<your-client-secret>'   # single-quote — secrets often contain $
```

Defaults for `fleet_redirect_uri`, `fleet_public_key_domain`, and `fleet_region` live in `config/default.yaml` — override them in `local.yaml` only if needed.

### Step 5: Partner-account registration (one-time)

```bash
uv run Tesla/tesla_auth.py --partner-login
```

This call validates the public key URL and binds your developer app to the domain. Expect HTTP 200 with a JSON response echoing your app name, domain, and `public_key_hash`.

If you see `412 invalid public key`, recheck Step 2's URL and content.

### Step 6: Mint user tokens (OAuth browser flow)

```bash
uv run Tesla/tesla_auth.py
```

What happens:

1. Browser opens to Tesla's consent screen
2. Sign in, complete MFA + hCaptcha
3. Approve the consent (Energy Product Information / Commands)
4. Tesla redirects to `http://localhost:8585/callback` — the script catches it
5. Tokens save to `lib/tokens/tesla_tokens.json` with 0o600 perms

### Step 7: Smoke test

```bash
uv run Tesla/manage_power.py 2>&1 | tee /tmp/tesla_smoke.log
```

You should see:

```
Connected to site: <your-site-name>
Battery: NN.NN%, Mode: ..., Export: battery_ok, Grid charge: True
```

---

## Configuration

### Decision Points

Configured in `config/default.yaml` under `tesla.decision_points`. Each entry:

```yaml
- time_start: 800           # HHMM
  time_end: 1200
  pct_thresh: 85.0
  pct_gradient_per_hr: 5.0
  iff_higher: true
  pct_min: 80.0
  pct_min_trail_stop: 0
  op_mode: backup           # backup | self_consumption | autonomous | storm_watch
  reason: "Morning solar charging"
  always_notify: false
```

### Token file shape

`lib/tokens/tesla_tokens.json` (0o600, gitignored):

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1781528068,
  "token_type": "Bearer"
}
```

Refresh is automatic before each API call when the access token is near expiry. Refresh-token rotation is persisted back to disk.

---

## Architecture

### Code layout

| File | Role |
|---|---|
| `manage_power.py` | Main monitoring loop, decision-point evaluation, Pushover alerts |
| `tesla_client.py` | Sync facade over `tesla-fleet-api` SDK. Preserves `TeslaAPIClient` + `BatteryProduct` interface — `manage_power.py` doesn't know it's async underneath |
| `tesla_auth.py` | OAuth browser flow (`uv run Tesla/tesla_auth.py`) + partner_accounts registration (`--partner-login`). Local HTTP server on `localhost:8585` catches the redirect |
| `test_manage_power.py` | Unit tests for `BatteryHistory`, `DecisionPoint`, `PowerwallManager` (no network) |

### Operation modes (Tesla nomenclature)

- `backup` — backup-only
- `self_consumption` — prefer self-consumption
- `autonomous` — autonomous time-of-use optimization
- `storm_watch` — maximum reserve during severe weather alerts

---

## Troubleshooting

### `Tesla token expired - run: uv run Tesla/tesla_auth.py`

Refresh token expired (>90 days unused) or revoked. Re-run the OAuth flow:

```bash
uv run Tesla/tesla_auth.py
```

### `412 invalid public key` on `--partner-login`

The URL `https://<domain>/.well-known/appspecific/com.tesla.3p.public-key.pem` isn't reachable or doesn't match the public key Tesla recorded at app-registration time. Re-verify with `curl -I` and check `.nojekyll` is present.

### `403 forbidden, see https://developer.tesla.com/docs/fleet-api`

The legacy Owner API host. Indicates the module fell back to old code or the SDK isn't installed. `BASE_URL` should never appear in `tesla_client.py` anymore. Reinstall with `uv sync`.

### `redirect_uri not registered for this client_id`

The redirect URI in `config/local.yaml` (`fleet_redirect_uri`) doesn't match what's registered at developer.tesla.com. Update one or the other so they match exactly (including trailing slash).

### `operation: None` in logs

Pre-existing artifact, not a Fleet API regression. The live-status endpoint sometimes omits `operation`. `manage_power.py` uses `cached_op_mode` as a fallback.

---

## References

- Tesla Fleet API docs: https://developer.tesla.com/docs/fleet-api
- `tesla-fleet-api` Python SDK: https://pypi.org/project/tesla-fleet-api/
- Home Assistant's Tesla Fleet integration (excellent reference for the onboarding flow): https://www.home-assistant.io/integrations/tesla_fleet/
- Migration plan that drove this implementation: `~/.claude/plans/uv-run-tesla-manage-power-py-is-cryptic-sloth.md`
