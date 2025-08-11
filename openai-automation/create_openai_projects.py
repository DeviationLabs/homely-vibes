#!/usr/bin/env python3
"""
Script to create OpenAI projects from a spreadsheet containing team names and email addresses.
Requires OpenAI API key with admin privileges.
"""

import csv
import json
import logging
import sys
from typing import List, Dict, Optional
import requests
import pandas as pd
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('openai_project_creation.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class OpenAIProjectManager:
    """Manages OpenAI project creation via API."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def create_project(self, name: str, description: str = "") -> Optional[Dict]:
        """Create a new OpenAI project."""
        url = f"{self.base_url}/organization/projects"
        
        payload = {
            "name": name,
            "description": description
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            
            project_data = response.json()
            logger.info(f"Successfully created project: {name} (ID: {project_data.get('id')})")
            return project_data
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create project {name}: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return None
    
    def set_project_budget(self, project_id: str, budget_limit: float = 200.0, alert_threshold: float = 0.5) -> bool:
        """Set budget limit and alert threshold for a project."""
        url = f"{self.base_url}/organization/projects/{project_id}/budget"
        
        payload = {
            "hard_limit_usd": budget_limit,
            "soft_limit_usd": budget_limit * alert_threshold
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            
            logger.info(f"Successfully set budget for project {project_id}: ${budget_limit} limit, ${budget_limit * alert_threshold:.2f} alert")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to set budget for project {project_id}: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return False
    
    def add_user_to_project(self, project_id: str, email: str, role: str = "member") -> bool:
        """Add a user to a project."""
        url = f"{self.base_url}/organization/projects/{project_id}/users"
        
        payload = {
            "email": email,
            "role": role
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()
            
            logger.info(f"Successfully added {email} to project {project_id}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to add user {email} to project {project_id}: {e}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response: {e.response.text}")
            return False
    
    def list_projects(self) -> List[Dict]:
        """List all existing projects."""
        url = f"{self.base_url}/organization/projects"
        
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            projects = response.json().get('data', [])
            logger.info(f"Found {len(projects)} existing projects")
            return projects
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to list projects: {e}")
            return []


def read_spreadsheet(file_path: str) -> List[Dict[str, str]]:
    """Read spreadsheet data (supports CSV and Excel formats)."""
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Spreadsheet file not found: {file_path}")
    
    try:
        if file_path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path)
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}")
        
        # Convert to list of dictionaries
        teams = df.to_dict('records')
        logger.info(f"Successfully read {len(teams)} teams from {file_path}")
        
        return teams
        
    except Exception as e:
        logger.error(f"Failed to read spreadsheet {file_path}: {e}")
        raise


def validate_team_data(teams: List[Dict]) -> List[Dict]:
    """Validate and clean team data."""
    valid_teams = []
    required_fields = ['team_name', 'email']
    
    for i, team in enumerate(teams):
        # Check if required fields exist (case-insensitive)
        team_lower = {k.lower(): v for k, v in team.items()}
        
        # Try common column name variations
        name_field = None
        email_field = None
        
        for key in team_lower.keys():
            if 'name' in key or 'team' in key:
                name_field = key
            if 'email' in key or 'mail' in key:
                email_field = key
        
        if not name_field or not email_field:
            logger.warning(f"Row {i+1}: Missing required fields. Skipping.")
            continue
        
        team_name = str(team_lower[name_field]).strip()
        email = str(team_lower[email_field]).strip()
        
        if not team_name or not email:
            logger.warning(f"Row {i+1}: Empty team name or email. Skipping.")
            continue
        
        # Basic email validation
        if '@' not in email or '.' not in email:
            logger.warning(f"Row {i+1}: Invalid email format '{email}'. Skipping.")
            continue
        
        valid_teams.append({
            'team_name': team_name,
            'email': email
        })
    
    logger.info(f"Validated {len(valid_teams)} out of {len(teams)} teams")
    return valid_teams


def main():
    """Main execution function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Create OpenAI projects from spreadsheet')
    parser.add_argument('spreadsheet', help='Path to spreadsheet file (CSV or Excel)')
    parser.add_argument('--api-key', help='OpenAI API key (or set OPENAI_API_KEY env var)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be created without actually creating')
    parser.add_argument('--description', default='Project created via automation script', 
                       help='Default description for created projects')
    parser.add_argument('--budget-limit', type=float, default=200.0,
                       help='Budget limit in USD for each project (default: $200)')
    parser.add_argument('--alert-threshold', type=float, default=0.5,
                       help='Budget alert threshold as fraction of limit (default: 0.5 = 50%%)')
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key
    if not api_key:
        import os
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logger.error("API key required. Use --api-key or set OPENAI_API_KEY environment variable")
            sys.exit(1)
    
    try:
        # Read and validate spreadsheet data
        teams = read_spreadsheet(args.spreadsheet)
        valid_teams = validate_team_data(teams)
        
        if not valid_teams:
            logger.error("No valid teams found in spreadsheet")
            sys.exit(1)
        
        if args.dry_run:
            logger.info("DRY RUN - Projects that would be created:")
            logger.info(f"Budget settings: ${args.budget_limit:.2f} limit, ${args.budget_limit * args.alert_threshold:.2f} alert (at {args.alert_threshold*100:.0f}%)")
            for team in valid_teams:
                logger.info(f"  - Project: {team['team_name']} (User: {team['email']})")
            sys.exit(0)
        
        # Initialize OpenAI API manager
        openai_manager = OpenAIProjectManager(api_key)
        
        # Get existing projects to avoid duplicates
        existing_projects = openai_manager.list_projects()
        existing_names = {proj['name'] for proj in existing_projects}
        
        # Create projects
        created_count = 0
        for team in valid_teams:
            team_name = team['team_name']
            email = team['email']
            
            # Check if project already exists
            if team_name in existing_names:
                logger.warning(f"Project '{team_name}' already exists. Skipping creation.")
                continue
            
            # Create project
            project = openai_manager.create_project(team_name, args.description)
            if project:
                project_id = project['id']
                
                # Set budget for the project
                budget_set = openai_manager.set_project_budget(
                    project_id, 
                    args.budget_limit, 
                    args.alert_threshold
                )
                
                # Add user to project
                user_added = openai_manager.add_user_to_project(project_id, email)
                
                if user_added and budget_set:
                    created_count += 1
                elif user_added:
                    logger.warning(f"Project created and user added, but budget setup failed for {team_name}")
                    created_count += 1
                else:
                    logger.warning(f"Project created but failed to add user {email}")
        
        logger.info(f"Successfully created {created_count} projects")
        
    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()