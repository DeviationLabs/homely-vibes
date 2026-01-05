# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

- **`lib/`**: Shared utilities (networking, notifications, logging, constants)
- **Component modules**: Tesla, RachioFlume, NetworkCheck, NodeCheck, BrowserAlert, August, SamsungFrame, etc.
- **AI/ML modules**: BimpopAI (RAG system), GarageCheck (computer vision)
- **Data processing**: WaterParser, WaterLogging

### Key Architectural Patterns

**Shared Library Pattern**: All modules use utilities from `lib/`:
- `lib/config.py` - Hydra-based hierarchical YAML configuration system
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

**Hydra Config System**: This project uses Hydra with hierarchical YAML configuration:
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

### Shared Library (`lib/`)
- **Config**: All modules source configuration from `lib/config.py` (Hydra-based hierarchical YAML)
- **Notifications**: Standardized via MyPushover, Mailer, MyTwilio classes
- **TeslaPy Submodule**: External dependency managed as Git submodule

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