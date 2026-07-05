# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Issue Tracking

We use **GitHub Issues** for tracking bugs, enhancements, and tech debt. Claude is responsible for filing and managing issues.

- File issues via `gh issue create` when bugs or improvements are discovered during sessions
- Labels: `bug`, `enhancement`, `tech-debt`
- Close issues from PRs when fixed
- Reference issue numbers in commit messages and PR descriptions

## Development Environment

**Package Manager**: This project uses `uv` for fast Python dependency management.

**Development Setup**:
```bash
make setup  # Installs Python 3.13.7, dependencies, Git submodules, and pre-commit hooks
```

**Common Commands**:
```bash
# Development workflow
make test           # Run all tests with pytest
make lint           # Run all linters (ruff, mypy, vulture, semgrep, codespell, deptry)
make hooks          # Set up pre-commit hooks
make clean          # Clean build artifacts and caches

# Individual tools
make ruff           # Code formatting and fixes
make mypy           # Type checking
make vulture        # Dead code detection
make semgrep        # Security analysis
make deptry         # Dependency analysis
make codespell      # Spell checking

# Test coverage
make coverage       # Run tests with coverage report
make coverage-html  # Generate HTML coverage report and open in browser
make coverage-lcov  # Generate lcov coverage report

# Docker environment (if needed)
make colima         # Start colima Docker environment with disk space checks

# Run specific modules
uv run python Tesla/manage_power_clean.py
uv run python RachioFlume/rfmanager.py
uv run python August/august_manager.py monitor
uv run python SamsungFrame/manage_samsung.py status
```

## Architecture Overview

### Module Organization
This is a **modular IoT home automation system** with independent components that share common utilities:

- **`lib/`**: Shared utilities (config, networking, notifications, logging, secret I/O, file lock)
- **Home / IoT modules**: August, NetworkCheck, NodeCheck, RachioFlume, RingBeams, RingSecurity, SamsungFrame, Tesla
- **AI / ML modules**: BimpopAI (RAG system), GarageCheck (computer vision), VoiceNotes (local STT)
- **Ops modules**: LaunchJobs (macOS launchd), PersonalCalSync (Google Apps Script), OpenAIAdmin, LambdaEmailFwder
- **Client / adjacent**: NoShorts (iOS app), VSCodeSidebarNotes (VS Code / Cursor extension), BrowserAlert, GPXParser

### Key Architectural Patterns

**Shared Library Pattern**: All modules use utilities from `lib/`:
- `lib/config.py` - OmegaConf-based hierarchical YAML configuration system
- `lib/logger.py` - Standardized logging
- `lib/MyPushover.py`, `lib/Mailer.py` - Notification services
- `lib/NetHelpers.py` - Network utilities

**Independent Modules**: Each component directory (Tesla/, RachioFlume/, etc.) operates independently but follows consistent patterns:
- Main script with CLI interface
- README.md with component-specific documentation
- Test files following pytest conventions
- Pydantic models for data validation

**Git Submodules**: External dependencies like TeslaPy are managed as submodules in `lib/TeslaPy/`

## Configuration Management

**OmegaConf Config System**: This project uses OmegaConf with hierarchical YAML configuration:
- `config/default.yaml` - Safe defaults (checked into git)
- `config/local.yaml` - Secrets and overrides (gitignored)
- `lib/config.py` - Dataclass-based structured configs with type safety

**Configuration Access Pattern**:
```python
from lib.config import get_config

cfg = get_config()
email = cfg.tesla.powerwall_email
tokens = cfg.pushover.tokens["Powerwall"]
```

**Hot Reload Support** (for long-running processes):
```python
from lib.config import reset_config, get_config

reset_config()  # Clear cached config
cfg = get_config()  # Reload from YAML
```

**Initial Setup**: Create `config/local.yaml` with your overrides (only add values you want to change):
```yaml
tesla:
  powerwall_email: your@email.com
  powerwall_password: your_password

pushover:
  user: your_pushover_user
  tokens:
    Powerwall: your_token
```

Config merges default.yaml + local.yaml hierarchically.

## Testing Strategy

**Test Organization**:
- Tests are co-located with source files (e.g., `Tesla/test_manage_power.py`)
- Use pytest with asyncio support for async components
- Test paths configured in pyproject.toml: `["Tesla", "RachioFlume", "NodeCheck", "August", "SamsungFrame"]`
- **Note**: NodeCheck tests run in isolation (separate pytest invocation) due to subprocess management patterns

**Running Tests**:
```bash
# All tests
make test

# Specific module tests
uv run python -m pytest Tesla/test_manage_power.py -v
uv run python -m pytest August/test_august_client.py -v
uv run python -m pytest SamsungFrame/test_samsung_client.py -v

# Specific test class
uv run python -m pytest RachioFlume/test_integration.py::TestFlumeClient -v

# Specific test function
uv run python -m pytest Tesla/test_manage_power.py::test_powerwall_manager -v

# NodeCheck runs in isolation (uses pytest-forked)
uv run pytest NodeCheck
```

## Code Quality Standards

**Linting Pipeline**: Pre-commit hooks automatically run on every commit:
- `make ruff` - Code formatting and linting
- `make test` - Full test suite execution
- `scripts/secret-scan.sh` - Secret scanning
- Conventional commit message format enforcement (e.g., `feat:`, `fix:`, `docs:`)

**Type Checking**: mypy with strict configuration (Python 3.13 target)
**Security**: semgrep for security analysis, secret-scan.sh for credential detection

**Code Style**:
- ruff formatting (100 char line length)
- ruff for linting and import sorting
- Exclude `lib/TeslaPy/` from linting (external submodule)

## Component-Specific Guidance

### Tesla Module (`Tesla/`)
- **Authentication**: Uses TeslaPy library, requires OAuth setup via `lib/TeslaPy/gui.py`
- **Main Features**: Powerwall monitoring, intelligent power management, battery history tracking
- **Key Classes**: PowerwallManager, BatteryHistory, DecisionPoint

### August Module (`August/`)
- **Authentication**: Requires 2FA via phone/email, tokens cached for ~7 days
- **Main Features**: Smart lock monitoring, unlock duration alerts, door ajar detection, battery warnings, lock failure detection
- **Initial Setup**: Run `august_manager.py test` to trigger 2FA, then use `validate_2fa.py` with verification code
- **Key Classes**: AugustManager with state persistence for alert tracking
- **Alert Thresholds**: Configurable via CLI (default: 5min unlock, 10min ajar, 20% battery)

### SamsungFrame Module (`SamsungFrame/`)
- **Authentication**: WebSocket token-based auth, saved to `config samsung_frame.token_file`
- **Main Features**: Image upload to Frame TV, matte/border management, slideshow control, art inventory management
- **Initial Setup**: First upload command triggers TV pairing prompt, token auto-saved for future use
- **Key Classes**: SamsungFrameClient, UploadResult (Pydantic), ImageUploadSummary
- **CLI Commands**: upload, status, list-art, list-mattes, download-thumbnails, update-mattes, cycle-images
- **Image Requirements**: JPG/PNG format, <10MB, validated before upload

### NodeCheck Module (`NodeCheck/`)
- **Purpose**: System node monitoring with continuous heartbeat tracking and automated device management
- **Testing**: Runs in isolation due to subprocess management patterns (uses pytest-forked)
- **Architecture**: Multi-process design requiring forked test execution to avoid state interference

### RachioFlume Module (`RachioFlume/`)
- **Integration**: Connects Rachio irrigation with Flume water monitoring
- **Architecture**: RachioClient, FlumeClient, WaterTrackingDB (SQLite), collector/reporter pattern
- **Usage**: `rfmanager.py` CLI with collect/status/report commands

### BimpopAI Module (`BimpopAI/`)
- **Architecture**: FastAPI backend + Streamlit frontend
- **Features**: RAG system with document indexing, conversational AI
- **Optional Dependencies**: Uses streamlit extra (`uv sync --extra streamlit`)

### VSCodeSidebarNotes Module (`VSCodeSidebarNotes/`)
- **Stack**: TypeScript VS Code / Cursor extension (NOT Python — does not use uv, pytest, or the rest of the repo's Python tooling).
- **Purpose**: Markdown sidebar that reads/writes `sidebar-notes.md` in the workspace root. Two-way sync with file watcher so Claude (or any external tool) can update the file and the sidebar refreshes live.
- **Build**: `cd VSCodeSidebarNotes && npm install && npm run compile` (esbuild → `dist/extension.js`). `npm run package-vsix` produces an installable `.vsix`.
- **Marketplace**: published under the `deviationlabs` publisher; see the module README for the publish flow.
- **Layout**: `package.json` (extension manifest), `src/` (TS source), `media/` (webview assets).

### Shared Library (`lib/`)
- **Config**: All modules source configuration from `lib/config.py` (OmegaConf-based hierarchical YAML)
- **Notifications**: Standardized via MyPushover, Mailer, MyTwilio classes
- **Secret I/O**: `lib/secure_io.py` — `write_secret_atomic(path, content)` for tokens we own (0o600 from birth), `ensure_secret_perms(path)` after third-party library writes (yalexs, SamsungTVWS). **All token/credential writes must go through these.**
- **TeslaPy Submodule**: External dependency managed as Git submodule

## Best Practices

Non-obvious rules that repeat across modules. Adhere to these in new code and PR reviews.

### Secrets on disk
- **Never `open(path, "w")` for a secret**, and never `write_text()` + `chmod`. Both leave a TOCTOU window at 0o644 under a 0o022 umask. Use `lib.secure_io.write_secret_atomic()` — it opens with `O_CREAT|O_TRUNC|0o600` so the file is world-unreadable from birth.
- If a **third-party library** writes the token (yalexs, SamsungTVWS, ring-client-api Node), immediately call `ensure_secret_perms(path)` after the call returns.
- Config files themselves live in `config/local.yaml` (gitignored). Tokens live under `config/tokens/` (symlinked to `~/bin/Common-configs/tokens/`, also gitignored on the code side).

### Alert priority discipline (Pushover)
Convention: `P{N}` maps 1:1 to Pushover `priority=N`. Every module README uses this scheme — the number IS the priority value, not a semantic tier.

- **P-1 (`priority=-1`)** — silent (no sound/vibration). Zone-end reports, informational clears, "act when convenient." Default for anything that doesn't need to interrupt.
- **P0 (`priority=0`)** — normal (default sound). Recovery/"cleared" transitions after a fire, non-urgent status change.
- **P1 (`priority=1`)** — high (bypasses quiet hours). Actionable within hours: low battery, service unreachable, hardware failure, partial sidecar failure, degraded network link.
- **P2 (`priority=2`)** — emergency (retries until acked). Reserve for water leaks, break-ins, sustained-flow rules firing — things where seconds matter. Don't cry wolf.
- **Auth failures land at P0**, not P1 or P2. Re-auth is a chore, not an emergency, but shouldn't be silent.

### Testing
- **Never `patch()` production code.** If a test needs to mock a subprocess/HTTP call, refactor the production code to accept the dependency as a parameter (factory or client). RingBeams's `run_sidecar(ring_factory=...)` is the reference pattern.
- **Fake sidecars via `sh` scripts** for subprocess boundaries. `.chmod(0o755)` + write a shebang + parametrize exit codes and stdout. Zero mocking, real subprocess semantics. See `RingBeams/test_beams_manager.py`.
- **Separate deterministic assertions** (exact values, structural matches) from anything that depends on wall-clock time or network state. Freeze time via fixtures if needed.
- **NodeCheck runs in isolation** — pytest-forked to avoid subprocess state leak into other suites.

### Sidecars & polyglot integration
- Node sidecars live inside the Python module (e.g., `RingBeams/fetch_status.js` alongside `beams_manager.py`).
- `node_modules/` is gitignored per-module; commit only `package.json` + `package-lock.json`.
- Sidecar exit-code contract must be explicit and documented at the top of the sidecar file. Python maps codes to Python exception classes; overloading `exit 1` for both auth failure and generic errors is the classic misclassification bug.
- Drain stdout before `process.exit(0)` — pass the exit callback to `process.stdout.write(payload, () => process.exit(0))`. On stdout-as-pipe, writes above ~16KB are buffered.
- Surface partial failures (per-location, per-device) in the JSON payload, not just stderr. Python only reads stderr on non-zero exit, so a silent partial with `exit 0` becomes a false "all healthy" report.

### Cron & deployment
- **Aibo (Linux prod) hosts homely_vibes at `~/Code`** — NOT `~/Documents/homely_vibes` as on the Mac. All aibo cron entries `cd ~/Code`.
- Cron entries redirect stdout+stderr to a file: `>> ~/logs/<script>.log 2>&1`. Never `> /dev/null` — you'd lose pre-logger crashes (import errors, `uv` failures, missing binaries).
- `lib.logger.get_logger()` sets up dual handlers (stdout + per-script log file under `cfg.paths.logging_dir`). Cron file redirection is the safety net for anything that happens before the logger initializes.
- Cron env needs `PATH` set for non-standard binaries (`node`, `uv`). Prepend `PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` at the top of the crontab, or use absolute paths in commands.

### Config changes
- Add a dataclass to `lib/config.py` for any new module's config, then register it in the root `Config` dataclass. Never `cfg_dict.get("your_key")` — the config system exists to give you type-checked access.
- `config/default.yaml` holds safe placeholders committed to git. `config/local.yaml` overrides with secrets and per-host values (gitignored, symlinked to `~/bin/Common-configs/Code_config_local.yaml`).
- If your module has multiple credentials, put them under a single top-level key (`ring:`, `august:`) so config diff reviews stay coherent.

### Git & PR flow
- Feature branches: `<gh-username>/feature-name`. Never work on `main`.
- Always `git fetch origin && git pull origin main` before creating a branch. Merging stale local `main` is the most common source of avoidable conflicts.
- Commit messages: conventional prefix (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`) enforced by pre-commit hook.
- **Never bypass pre-commit hooks** (`--no-verify`) unless the hook itself is broken (rare) — investigate the underlying failure. If hooks conflict with staged changes on ruff auto-fix, run `uv run ruff format` manually first, then re-stage.
- **PR review comment threads**: read → fix → push → reply *inside each thread* → resolve thread. `gh pr comment` alone is not the right tool — reviewers won't see the reply attached to their concern.

## Development Workflow

1. **Start with setup**: `make setup` to ensure environment is consistent
2. **Pre-commit automation**: Pre-commit hooks automatically run `make ruff` and `make test` on every commit
   - Hooks also enforce conventional commit message format
   - Use `git commit -m "type: description"` format (e.g., `feat:`, `fix:`, `docs:`)
3. **Test locally**: `make test` before pushing changes
4. **Module isolation**: Each component can be developed independently
5. **Shared utilities**: Prefer extending `lib/` utilities over duplicating code

## Key Dependencies

- **Python 3.13+**: Required for async features and modern typing
- **uv**: Package manager for fast installs and dependency resolution
- **pydantic**: Data validation across all modules
- **pytest + asyncio**: Testing framework with async support
- **ruff + mypy**: Code quality and type checking