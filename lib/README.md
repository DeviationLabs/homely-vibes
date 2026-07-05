# lib/ — shared utilities

Shared library used by all homely-vibes modules. Config, logging, notifications, networking, secret I/O, and cross-process locking.

## Modules

### `config.py` — typed configuration
OmegaConf-based hierarchical YAML config with dataclass-backed type safety.

- `config/default.yaml` — safe defaults, checked into git
- `config/local.yaml` — secrets + per-host overrides, gitignored (symlinked to `~/bin/Common-configs/Code_config_local.yaml`)
- Merged hierarchically; `local.yaml` wins.

```python
from lib.config import get_config, reset_config

cfg = get_config()
email = cfg.tesla.powerwall_email
tokens = cfg.pushover.tokens["Powerwall"]

# Long-running processes: hot-reload between cycles
reset_config()
cfg = get_config()
```

**Adding a module's config:** add a dataclass, register it in the root `Config` dataclass, add a `your_module:` block to `config/default.yaml`. Never `cfg_dict.get("key")` — the system exists to give type-checked access.

Public API: `get_config() -> Config`, `reset_config() -> None`, `Config` (root dataclass).

### `logger.py` — dual-handler logging
```python
from lib.logger import get_logger
logger = get_logger(__name__)
```
`get_logger` sets up stdout + a per-script log file under `cfg.paths.logging_dir`. The script name is derived from `__main__.__file__` so each entrypoint gets its own log file. `SystemLogger.reset()` / `set_level()` available for testing/runtime control.

Cron entries redirect stdout+stderr to a file (`>> ~/logs/<script>.log 2>&1`) as a safety net for anything that happens before the logger initializes.

### `MyPushover.py` — Pushover notifications
```python
from lib.MyPushover import Pushover
pushover = Pushover(cfg.pushover.user, cfg.pushover.tokens["YourModule"])
pushover.send_message("msg", title="Title", priority=1)
```
Priority convention (`P{N}` = Pushover `priority=N`): **P-1** silent, **P0** normal/recovery, **P1** high (bypasses quiet hours), **P2** emergency (retries until acked). Auth failures land at P0.

### `Mailer.py` — Gmail SMTP
```python
from lib.Mailer import sendmail
sendmail("topic", alert=True, message="<html>...</html>")
```
Sends via `smtp.gmail.com:465` (SSL) using `cfg.email.*`. HTML detected by `<html>` prefix; otherwise plain UTF-8. Honors an `always_email` flag and a per-call `alert` boolean (no-op when neither is set).

### `MyTwilio.py` — SMS via Twilio
```python
from lib.MyTwilio import sendsms
sendsms(rcpt="+1...", msg="text")
```
Uses `cfg.twilio.*`. Logs the message SID on success.

### `NetHelpers.py` — network/SSH utilities
- `ping_output(node, count=1, desired_up=True) -> bool` — subprocess ping with timeout.
- `ssh_connect(ip, user, passwd) -> SSHClient`, `ssh_cmd_v2(client, cmd) -> str` — paramiko.
- `ssh_cmd(node, user, passwd, winCmd) -> str` — connect + run + close in one call.
- `http_req(cmd) -> str`, `no_stdout()` context manager, `redirect_to_file(text)`.

### `secure_io.py` — atomic 0o600 secret writes
**Never** `open(path, "w")` / `write_text()` + `chmod` for a secret — both leave a TOCTOU window at 0o644 under a 0o022 umask.

```python
from lib.secure_io import write_secret_atomic, ensure_secret_perms
# We own the write — 0o600 from birth:
write_secret_atomic(path, {"access_token": "...", "expires_at": 123})

# Third-party library owns the write — tighten perms after it returns:
ensure_secret_perms(path)
```
Accepts `str | bytes | dict` (dict is JSON-encoded). Both are idempotent on existing 0o600 files.

### `file_lock.py` — POSIX advisory flock
Cross-process critical sections. Used to serialize Ring token refresh across RingSecurity (Python) and RingBeams (Node sidecar) — both read/write `config/tokens/ring_auth_token.json` and Ring OAuth rotates the refresh_token on every use, so overlapping refreshes race the server.

```python
from lib.file_lock import acquire_lock, LockTimeoutError
with acquire_lock(token_path, timeout_s=60.0):
    # exclusive access across processes
    ...
```
Locks a sibling `<path>.lock` file (NOT the resource — the resource is rewritten via tmp+rename, so an fd on the pre-rename inode would dangle). Auto-released on exit/crash. Raises `LockTimeoutError(TimeoutError)` if not acquired in time.

## Submodules
- `lib/TeslaPy/` — legacy Tesla SDK, git submodule, excluded from linting. (Tesla module now uses Fleet API; submodule retained for history.)

## Conventions
- **No `patch()` in tests.** Refactor production code to accept the dependency as a parameter (factory or client). Inject fakes that satisfy a `Protocol` or duck-type the surface.
- **Secrets live in `config/tokens/`** (symlinked to `~/bin/Common-configs/tokens/`, gitignored). Config values in `config/local.yaml` (gitignored).
- **New module config → dataclass in `config.py` + default.yaml block.** Never ad-hoc `get()`.

## Tests
```bash
uv run python -m pytest lib/ -v
```
`test_file_lock.py`, `test_secure_io.py` — deterministic, no network.
