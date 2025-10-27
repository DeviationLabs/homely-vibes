# Homely Vibes - IoT Home Automation

A comprehensive home automation and monitoring system with Python-based IoT integrations, ML-powered analytics, and smart device management.

<div class="btn-group">
  <a href="https://github.com/abutala/homely-vibes" class="btn-custom btn-secondary" title="View source code and contribute on GitHub">💻 View on GitHub</a>
</div>

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
make lint           # Check code quality

# Code formatting and linting
make lint-fix        # Fix all linting issues

# Run specific services (see individual folder READMEs for details)
uv run python Tesla/manage_power_clean.py
uv run python RachioFlume/main.py
```

## Project Components

| Component | Description | Documentation |
|:----------|:------------|:-------------:|
| 🔐 **August** | August Smart Lock monitoring with automated unlock alerts and pushover notifications for home security. | [📖 Read More](https://github.com/abutala/homely-vibes/blob/main/August/README.md) |
| 🤖 **Bimpop.ai** | RAG (Retrieval Augmented Generation) system with AI voice assistant, indexing, and Streamlit frontend. A startup concept for business intelligence in Mom-n-Pop stores. | [📖 Read More](https://github.com/abutala/homely-vibes/blob/main/Bimpop.ai/README.md) |
| 🌐 **BrowserAlert** | Web usage monitoring and alerting system for tracking browsing activity and digital wellness. | [📖 Read More](https://github.com/abutala/homely-vibes/blob/main/BrowserAlert/README.md) |
| 🚗 **GarageCheck** | Machine learning-based garage door status detection using image classification and computer vision. | - |
| 🗺️ **GpxParser** | GPX track analysis and processing tools for GPS data visualization and route analysis. | - |
| 🔑 **JWTs** | JWT token extraction and analysis utilities for HAR files and authentication workflows. | - |
| 📧 **LambdaEmailFwder** | AWS Lambda function for automated email forwarding and intelligent message processing. | - |
| 🌐 **NetworkCheck** | Network uplink testing and connectivity monitoring utilities for reliable internet connections. | - |
| 🖥️ **NodeCheck** | System node monitoring with continuous heartbeat tracking and automated device management. | [📖 Read More](https://github.com/abutala/homely-vibes/blob/main/NodeCheck/README.md) |
| 🔧 **OpenAIAdmin** | OpenAI project management and administration tools for API governance and usage tracking. | - |
| 💧 **RachioFlume** | Water usage tracking integration between Rachio irrigation systems and Flume water monitoring. | [📖 Read More](https://github.com/abutala/homely-vibes/blob/main/RachioFlume/README.md) |
| ⚡ **Tesla** | Tesla Powerwall monitoring and intelligent power management automation for home energy optimization. | - |
| 📊 **WaterLogging** | Comprehensive data collection scripts for Rachio, Flume, and Tuya smart water devices. | - |
| 📈 **WaterParser** | Advanced water usage data processing, statistical analysis, and interactive HTML report generation. | - |
| 🛠️ **lib** | Shared utilities library for email, push notifications, networking, and essential system helpers. | - |
