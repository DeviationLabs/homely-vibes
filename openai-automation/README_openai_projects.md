# OpenAI Project Creation Script

This script automates the creation of OpenAI projects from a spreadsheet containing team names and email addresses.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Set your OpenAI API key:
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```

## Usage

### Basic Usage
```bash
python create_openai_projects.py sample_teams.csv
```

### With API key as argument
```bash
python create_openai_projects.py sample_teams.csv --api-key "your-api-key"
```

### Dry run (preview without creating)
```bash
python create_openai_projects.py sample_teams.csv --dry-run
```

### Custom project description
```bash
python create_openai_projects.py sample_teams.csv --description "Custom project description"
```

### Custom budget settings
```bash
# Set $150 budget limit with alert at 60% ($90)
python create_openai_projects.py sample_teams.csv --budget-limit 150 --alert-threshold 0.6

# Set $300 budget with default 50% alert threshold
python create_openai_projects.py sample_teams.csv --budget-limit 300
```

## Spreadsheet Format

The script supports multiple spreadsheet formats and automatically detects the column structure:

### HackWeek Format (Preferred)
The script automatically detects HackWeek CSV format with these key columns:
- **Project Name**: `"Give us a project name in slug format (e.g: lms-support-bot, hris-data-inspector)"`  
- **Email**: `"Email Address"`

### Legacy Format (Backwards Compatible)
For simple CSV files, the script supports these column name variations:
- **Team Name**: `team_name`, `team`, `name`, `project_name`
- **Email**: `email`, `mail`, `user_email`

### Supported Formats
- CSV files (`.csv`)
- Excel files (`.xlsx`, `.xls`)

### Example HackWeek CSV:
```csv
Timestamp,Email Address,Your Full Name,Your Team/Department,Which AI tools are you requesting access to?,"Give us a project name in slug format (e.g: lms-support-bot, hris-data-inspector)",Please provide a brief description of how you plan to use these tools during Hack Week.,What is your prior experience level with AI tools?,Do you require any specific training or resources to effectively use these tools?,"If yes, please elaborate on your training/resource needs."
8/11/2025 10:15:22,jsmith@company.com,John Smith,Frontend Engineering,OpenAI,ui-component-generator,Build an AI-powered component library,Intermediate,Yes,Need guidance on prompt engineering
```

### Example Legacy CSV:
```csv
team_name,email
Engineering Team Alpha,alpha@company.com
Marketing Team Beta,beta@company.com
```

## Features

- ✅ Reads CSV and Excel files
- ✅ Validates email addresses
- ✅ Checks for duplicate project names
- ✅ Comprehensive error handling and logging
- ✅ Dry-run mode for testing
- ✅ Adds users to created projects
- ✅ Sets budget limits and alerts ($200 limit, 50% alert by default)
- ✅ Progress logging to file and console

## Logging

The script creates a log file `openai_project_creation.log` with detailed information about:
- Projects created successfully
- Budget limits and alerts configured
- Users added to projects
- Errors and warnings
- Validation issues

## Error Handling

The script handles various error scenarios:
- Missing or invalid spreadsheet files
- Invalid email formats
- API errors
- Duplicate project names
- Missing required columns