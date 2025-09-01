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
make lint-fix       # Auto-fix linting issues where possible

# Individual tools
make ruff           # Code formatting and fixes
make ruff-check     # Check code style without fixes
make mypy           # Type checking
make vulture        # Dead code detection
make semgrep        # Security analysis
make deptry         # Dependency analysis

# Run specific modules
uv run python Tesla/manage_power_clean.py
uv run python RachioFlume/rfmanager.py
```

## Architecture Overview

### Module Organization
This is a **modular IoT home automation system** with independent components that share common utilities:

- **`lib/`**: Shared utilities (networking, notifications, logging, constants)
- **Component modules**: Tesla, RachioFlume, NetworkCheck, NodeCheck, BrowserAlert, etc.
- **AI/ML modules**: Bimpop.ai (RAG system), GarageCheck (computer vision)
- **Data processing**: WaterParser, WaterLogging

### Key Architectural Patterns

**Shared Library Pattern**: All modules use utilities from `lib/`:
- `lib/Constants.py` - Centralized configuration (API keys, settings)
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

**Credentials**: Use `lib/Constants.py` (not environment variables) for API keys and configuration.
**Template**: Copy `lib/Constants_sample.py` to `lib/Constants.py` for initial setup.

## Testing Strategy

**Test Organization**:
- Tests are co-located with source files (e.g., `Tesla/test_manage_power.py`)
- Use pytest with asyncio support for async components
- Test paths configured in pyproject.toml: `["Tesla", "WaterParser", "Bimpop.ai"]`

**Running Tests**:
```bash
# All tests
make test

# Specific module tests
uv run python -m pytest Tesla/test_manage_power.py -v
uv run python -m pytest RachioFlume/test_integration.py::TestFlumeClient -v
```

## Code Quality Standards

**Linting Pipeline**: Pre-commit hooks run ruff formatting and secret scanning.
**Type Checking**: mypy with strict configuration (Python 3.13 target)
**Security**: semgrep for security analysis, secret-scan.sh for credential detection

**Code Style**:
- Black formatting (88 char line length)
- ruff for linting and import sorting
- Exclude `lib/TeslaPy/` from linting (external submodule)

## Component-Specific Guidance

### Tesla Module (`Tesla/`)
- **Authentication**: Uses TeslaPy library, requires OAuth setup via `lib/TeslaPy/gui.py`
- **Main Features**: Powerwall monitoring, intelligent power management, battery history tracking
- **Key Classes**: PowerwallManager, BatteryHistory, DecisionPoint

### RachioFlume Module (`RachioFlume/`)
- **Integration**: Connects Rachio irrigation with Flume water monitoring
- **Architecture**: RachioClient, FlumeClient, WaterTrackingDB (SQLite), collector/reporter pattern
- **Usage**: `rfmanager.py` CLI with collect/status/report commands

### Bimpop.ai Module (`Bimpop.ai/`)
- **Architecture**: FastAPI backend + Streamlit frontend
- **Features**: RAG system with document indexing, conversational AI
- **Optional Dependencies**: Uses streamlit extra (`uv sync --extra streamlit`)

### Shared Library (`lib/`)
- **Constants**: All modules source configuration from `lib/Constants.py`
- **Notifications**: Standardized via MyPushover, Mailer, MyTwilio classes
- **TeslaPy Submodule**: External dependency managed as Git submodule

## Development Workflow

1. **Start with setup**: `make setup` to ensure environment is consistent
2. **Run linters before commits**: Pre-commit hooks enforce formatting
3. **Test locally**: `make test` before pushing changes  
4. **Module isolation**: Each component can be developed independently
5. **Shared utilities**: Prefer extending `lib/` utilities over duplicating code

## Key Dependencies

- **Python 3.13+**: Required for async features and modern typing
- **uv**: Package manager for fast installs and dependency resolution
- **pydantic**: Data validation across all modules
- **pytest + asyncio**: Testing framework with async support
- **ruff + mypy**: Code quality and type checking