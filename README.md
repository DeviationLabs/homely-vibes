# Homely Vibes - IoT Home Automation

A comprehensive home automation and monitoring system with Python-based IoT integrations, ML-powered analytics, and smart device management.

<div class="btn-group">
  <a href="#quick-start" class="btn">Get Started</a>
  <a href="https://github.com/abutala/homely-vibes" class="btn btn-secondary">View on GitHub</a>
</div>

## Quick Start
{: .quick-start}

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

<div class="project-grid">
  <div class="project-card">
    <h3>🤖 Bimpop.ai</h3>
    <p>RAG (Retrieval Augmented Generation) system with AI voice assistant, indexing, and Streamlit frontend. A startup concept for business intelligence in Mom-n-Pop stores.</p>
  </div>
  
  <div class="project-card">
    <h3>🌐 BrowserAlert</h3>
    <p>Web usage monitoring and alerting system for tracking browsing activity and digital wellness.</p>
  </div>
  
  <div class="project-card">
    <h3>🚗 GarageCheck</h3>
    <p>Machine learning-based garage door status detection using image classification and computer vision.</p>
  </div>
  
  <div class="project-card">
    <h3>📧 LambdaEmailFwder</h3>
    <p>AWS Lambda function for automated email forwarding and intelligent message processing.</p>
  </div>
  
  <div class="project-card">
    <h3>🌐 NetworkCheck</h3>
    <p>Network uplink testing and connectivity monitoring utilities for reliable internet connections.</p>
  </div>
  
  <div class="project-card">
    <h3>🖥️ NodeCheck</h3>
    <p>System node monitoring, Foscam camera management, and automated reboot coordination.</p>
  </div>
  
  <div class="project-card">
    <h3>🔧 OpenAIAdmin</h3>
    <p>OpenAI project management and administration tools for API governance and usage tracking.</p>
  </div>
  
  <div class="project-card">
    <h3>💧 RachioFlume</h3>
    <p>Water usage tracking integration between Rachio irrigation systems and Flume water monitoring.</p>
  </div>
  
  <div class="project-card">
    <h3>⚡ Tesla</h3>
    <p>Tesla Powerwall monitoring and intelligent power management automation for home energy optimization.</p>
  </div>
  
  <div class="project-card">
    <h3>📊 WaterLogging</h3>
    <p>Comprehensive data collection scripts for Rachio, Flume, and Tuya smart water devices.</p>
  </div>
  
  <div class="project-card">
    <h3>📈 WaterParser</h3>
    <p>Advanced water usage data processing, statistical analysis, and interactive HTML report generation.</p>
  </div>
  
  <div class="project-card">
    <h3>🛠️ lib</h3>
    <p>Shared utilities library for email, push notifications, networking, and essential system helpers.</p>
  </div>
</div>
