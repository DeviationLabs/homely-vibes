# Homely Vibes - IoT Home Automation

A comprehensive home automation and monitoring system with Python-based IoT integrations, ML-powered analytics, and smart device management.

## Quick Start

### Prerequisites
- Python 3.13+ (managed via pyenv)
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager
- [pre-commit](https://pre-commit.com/) - Git hooks for code quality

### Installation

```bash
# Clone the repository
git clone https://github.com/abutala/homely-vibes.git
cd homely-vibes

# Setup development environment (installs Python 3.13.7, dependencies, and git hooks)
make setup

# Or manual setup:
pyenv install 3.13.7 && pyenv local 3.13.7
uv sync --extra dev
pre-commit install
```

### Development

```bash
# Run all tests
make test

# Code formatting and linting
make lint-fix        # Fix all linting issues
make ruff-format     # Format code
make lint           # Check code quality

# Run specific services (see individual folder READMEs for details)
uv run python Tesla/manage_power_clean.py
uv run python RachioFlume/main.py
```

## Folder Descriptions

- **Bimpop.ai/** - RAG (Retrieval Augmented Generation) system with AI voice assistant, indexing, and Streamlit frontend. This was a startup idea - Business intelligence for `Mom-n-Pop` stores. 
- **BrowserAlert/** - Web usage monitoring and alerting system for tracking browsing activity
- **GarageCheck/** - Machine learning-based garage door status detection using image classification
- **LambdaEmailFwder/** - AWS Lambda function for email forwarding and processing
- **NetworkCheck/** - Network uplink testing and connectivity monitoring utilities
- **NodeCheck/** - System node monitoring, Foscam camera management, and reboot automation
- **OpenAIAdmin/** - OpenAI project management and administration tools
- **RachioFlume/** - Water usage tracking integration between Rachio irrigation and Flume water monitoring
- **Tesla/** - Tesla Powerwall monitoring and power management automation
- **WaterLogging/** - Data collection scripts for Rachio, Flume, and Tuya smart devices
- **WaterParser/** - Water usage data processing, analysis, and HTML report generation
- **lib/** - Shared utilities for email, push notifications, networking, and system helpers
