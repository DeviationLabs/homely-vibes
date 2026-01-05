# Agent Configurations for Homely Vibes

This document defines specialized AI agents for the Homely Vibes IoT home automation system. These agents help manage different components and provide focused expertise for specific domains.

## IoT Device Management Agents

### Tesla Energy Agent
**Scope**: Tesla Powerwall monitoring and intelligent power management
- **Files**: `Tesla/manage_power_clean.py`, `Tesla/test_manage_power_clean.py`
- **Capabilities**: Energy optimization, battery monitoring, power usage analytics
- **Dependencies**: TeslaPy library, authentication tokens
- **Use for**: Powerwall status checks, energy scheduling, cost optimization

### Water Management Agent  
**Scope**: Rachio irrigation and Flume water monitoring integration
- **Files**: `RachioFlume/rfmanager.py`, `WaterLogging/`, `WaterParser/`
- **Capabilities**: Water usage tracking, irrigation scheduling, leak detection
- **Dependencies**: Rachio API, Flume API, Tuya device integration
- **Use for**: Water conservation, usage analytics, smart irrigation

### Network Monitoring Agent
**Scope**: Network connectivity and system health monitoring
- **Files**: `NetworkCheck/`, `NodeCheck/`, `BrowserAlert/`
- **Capabilities**: Uplink testing, device monitoring, alert management
- **Dependencies**: Network utilities, Foscam cameras, notification systems
- **Use for**: Connectivity issues, system health checks, security monitoring

## AI/ML Specialized Agents

### Bimpop RAG Agent
**Scope**: Business intelligence and voice assistant functionality
- **Files**: `Bimpop.ai/app/main.py`, `Bimpop.ai/fe/streamlit_app.py`
- **Capabilities**: Document indexing, conversational AI, sentiment analysis
- **Dependencies**: FastAPI, Streamlit, voice recognition APIs
- **Use for**: Business analytics, customer insights, AI-powered interfaces

### Computer Vision Agent
**Scope**: Image processing and visual monitoring
- **Files**: `GarageCheck/`, `lib/FoscamImager.py`
- **Capabilities**: Image classification, garage door detection, camera management
- **Dependencies**: OpenCV, ML models, Foscam camera APIs
- **Use for**: Visual monitoring, automated detection, security cameras

## Infrastructure & Communication Agents

### Notification Agent
**Scope**: Multi-channel alert and communication management
- **Files**: `lib/MyPushover.py`, `lib/MyTwilio.py`, `lib/Mailer.py`
- **Capabilities**: Push notifications, SMS, email, alert routing
- **Dependencies**: Pushover API, Twilio API, SMTP services
- **Use for**: Alert delivery, status updates, emergency notifications

### Cloud Integration Agent
**Scope**: AWS services and serverless functions
- **Files**: `LambdaEmailFwder/`, `OpenAIAdmin/`
- **Capabilities**: Email forwarding, OpenAI project management, cloud automation
- **Dependencies**: AWS Lambda, OpenAI API, cloud service credentials
- **Use for**: Email processing, API management, serverless workflows

## Development & Operations Agents

### Testing & Quality Agent
**Scope**: Code quality, testing, and development workflow
- **Files**: Test files, `Makefile`, linting configurations
- **Capabilities**: Test execution, code formatting, quality checks
- **Dependencies**: pytest, ruff, pre-commit hooks
- **Use for**: CI/CD, code reviews, quality assurance

### Data Processing Agent
**Scope**: Data analysis and report generation
- **Files**: `WaterParser/`, analytics scripts
- **Capabilities**: Statistical analysis, HTML reports, data visualization
- **Dependencies**: Data processing libraries, charting tools
- **Use for**: Usage analytics, trend analysis, automated reporting

## Agent Interaction Patterns

### Cross-Agent Communication
- Agents share common utilities from `lib/` directory
- Centralized logging via `lib/logger.py`
- Shared configuration via Hydra (`lib/config.py` + `config/local.yaml`)

### Security Considerations
- All agents use secure credential management
- No hardcoded secrets (use environment variables)
- Input validation for all external data sources

### Deployment Strategy
- Agents can run independently or in orchestrated workflows
- Use `make setup` for consistent development environment
- Follow uv-based dependency management

## Usage Guidelines

1. **Single Responsibility**: Each agent focuses on one domain
2. **Loose Coupling**: Agents communicate via shared interfaces
3. **Error Handling**: All agents implement robust error recovery
4. **Monitoring**: Centralized logging and alerting for all agents
5. **Testing**: Each agent has comprehensive test coverage

## Getting Started

```bash
# Setup development environment
make setup

# Run specific agent components
uv run python Tesla/manage_power_clean.py
uv run python RachioFlume/rfmanager.py

# Test all components
make test
```

For detailed component-specific documentation, see the README files in each module directory.