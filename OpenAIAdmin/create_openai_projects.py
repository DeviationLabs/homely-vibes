#!/usr/bin/env python3
"""
Script to create OpenAI projects from a spreadsheet containing team names and email addresses.
Requires OpenAI API key with admin privileges.
"""

import logging
import sys
from typing import List, Dict, Optional
import requests
import pandas as pd
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("openai_project_creation.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class OpenAIProjectManager:
    """Manages OpenAI project creation via API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def create_project(self, name: str, description: str = "") -> Optional[Dict]:
        """Create a new OpenAI project."""
        url = f"{self.base_url}/organization/projects"

        payload = {"name": name, "description": description}

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()

            project_data = response.json()
            logger.info(f"Successfully created project: {name} (ID: {project_data.get('id')})")
            return project_data

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create project {name}: {e}")
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "text"):
                logger.error(f"Response: {e.response.text}")
            return None

    def set_project_budget(
        self,
        project_id: str,
        project_name: str,
        budget_limit: float = 200.0,
        alert_threshold: float = 0.5,
    ) -> bool:
        """Set budget limit and alert threshold for a project."""
        url = f"{self.base_url}/organization/projects/{project_id}/budget"

        # Try different payload formats based on OpenAI API docs
        payload = {
            "hard_limit_usd": budget_limit,
            "soft_limit_usd": budget_limit * alert_threshold,
        }

        try:
            # Try PUT method as budgets might be configuration updates
            response = requests.put(url, headers=self.headers, json=payload)
            response.raise_for_status()

            logger.info(
                f"Successfully set budget for project {project_id}: ${budget_limit} limit, ${budget_limit * alert_threshold:.2f} alert"
            )
            return True

        except requests.exceptions.RequestException as e:
            logger.warning(
                f"Budget setting may not be available via API for project {project_id}: {e}"
            )
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "text"):
                logger.debug(f"Response: {e.response.text}")
            # Don't treat budget setting failure as a critical error
            return True  # Consider it successful so project creation continues

    def get_user_id_from_email(self, email: str) -> Optional[str]:
        """Get user ID from email address with pagination."""
        url = f"{self.base_url}/organization/users"

        try:
            after = None
            while True:
                params = {"limit": 100}
                if after:
                    params["after"] = after

                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()

                users_data = response.json()
                users = users_data.get("data", [])

                # Search for user in current page
                for user in users:
                    if user.get("email", "").lower() == email.lower():
                        return user.get("id")

                # Check if there are more pages
                if not users_data.get("has_more", False) or not users:
                    break

                # Get cursor for next page
                after = users[-1].get("id")

            logger.warning(
                f"User with email {email} not found in organization - they may need to be invited first"
            )
            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to lookup user {email}: {e}")
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "text"):
                logger.error(f"Response: {e.response.text}")
            return None

    def invite_user_to_organization(self, email: str, role: str = "reader") -> bool:
        """Invite a user to the organization."""
        url = f"{self.base_url}/organization/invites"

        payload = {"email": email, "role": role}

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()

            logger.info(f"Successfully invited {email} to organization with role {role}")
            return True

        except requests.exceptions.RequestException as e:
            # Check if the error is because the invite already exists or user already exists
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "text"):
                error_text = e.response.text.lower()

                # If user already has an invite, this is actually a success case
                if ("already" in error_text and "invited" in error_text) or (
                    "pending" in error_text
                ):
                    logger.info(
                        f"User {email} already has a pending invitation to the organization"
                    )
                    return True  # Treat as success since invitation exists

                # If user already exists (but with a different case or format), this might be a success case
                if "already" in error_text and "exists" in error_text:
                    logger.info(
                        f"User with email similar to {email} may already exist in the organization"
                    )
                    return True  # Treat as partial success

                logger.error(f"Failed to invite user {email} to organization: {e}")
                logger.error(f"Response: {e.response.text}")
            else:
                logger.error(f"Failed to invite user {email} to organization: {e}")
            return False

    def add_user_to_project(
        self,
        project_id: str,
        email: str,
        role: str = "member",
        auto_invite: bool = True,
    ) -> bool:
        """Add a user to a project."""
        # First get the user ID from email
        user_id = self.get_user_id_from_email(email)
        if not user_id:
            if auto_invite:
                logger.info(
                    f"User {email} not found in organization, attempting to invite them first..."
                )
                invite_success = self.invite_user_to_organization(email, "reader")
                if invite_success:
                    logger.info(
                        f"User {email} invited successfully. They will need to accept the invitation before being added to projects."
                    )
                    return True  # Consider this a success even though they need to accept the invitation
                else:
                    # Check if the invite failed because it already exists (which is still a success case)
                    logger.warning(
                        f"Could not invite user {email} - they may already have a pending invitation"
                    )
                    return True  # Consider this a success since they might already have an invite
            else:
                logger.warning(
                    f"Cannot add user {email} - user ID not found (auto-invite disabled)"
                )
                return False

        # Check if user already exists in the project
        current_role = self.get_user_project_role(project_id, user_id)
        if current_role:
            # User already exists in project, check if we need to update the role
            if current_role != role and role == "owner":
                logger.info(
                    f"User {email} is already in project with role {current_role}, updating to {role}"
                )
                update_success = self.update_user_project_role(project_id, user_id, role)
                if update_success:
                    logger.info(
                        f"Successfully updated {email} to role {role} in project {project_id}"
                    )
                    return True
                else:
                    logger.error(f"Failed to update {email} to role {role} in project {project_id}")
                    return False
            else:
                # User already has the correct role or is an owner and we're trying to downgrade
                logger.info(
                    f"User {email} already exists in project with role {current_role}, no change needed"
                )
                return True

        # Add user to project
        url = f"{self.base_url}/organization/projects/{project_id}/users"

        payload = {"user_id": user_id, "role": role}

        try:
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()

            logger.info(f"Successfully added {email} to project {project_id} with role {role}")
            return True

        except requests.exceptions.RequestException as e:
            # Handle various error scenarios gracefully
            if hasattr(e, "response") and e.response is not None:
                if e.response.status_code == 400 and hasattr(e.response, "text"):
                    error_text = e.response.text.lower()

                    # Check for pending invite scenarios
                    if "pending" in error_text and "invite" in error_text:
                        logger.info(
                            f"User {email} has a pending invitation to the organization. They will need to accept before being added to projects."
                        )
                        return True  # Consider this a success since the invitation process is in progress

                    # Check if user already exists in project (common scenario, not an error)
                    if "already" in error_text or "exists" in error_text or "member" in error_text:
                        # User exists but we couldn't detect this earlier, try updating role
                        if role == "owner":
                            logger.info(
                                f"User {email} already exists in project {project_id}, attempting to update role to {role}"
                            )
                            update_success = self.update_user_project_role(
                                project_id, user_id, role
                            )
                            if update_success:
                                logger.info(
                                    f"Successfully updated {email} to role {role} in project {project_id}"
                                )
                                return True
                        # If we're not trying to update to owner or update failed, just continue
                        logger.info(
                            f"User {email} already exists in project {project_id}, continuing..."
                        )
                        return True  # Treat as success since user is already in project

                logger.error(f"Failed to add user {email} to project {project_id}: {e}")
                logger.error(f"Response: {e.response.text}")
            else:
                logger.error(f"Failed to add user {email} to project {project_id}: {e}")
            return False

    def get_user_project_role(self, project_id: str, user_id: str) -> Optional[str]:
        """Get a user's current role in a project."""
        url = f"{self.base_url}/organization/projects/{project_id}/users"

        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()

            users_data = response.json()
            users = users_data.get("data", [])

            # Find the user in the project users list
            for user in users:
                if user.get("id") == user_id:
                    return user.get("role")

            # User not found in project
            return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get users for project {project_id}: {e}")
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "text"):
                logger.error(f"Response: {e.response.text}")
            return None

    def update_user_project_role(self, project_id: str, user_id: str, role: str) -> bool:
        """Update a user's role in a project using POST request."""
        url = f"{self.base_url}/organization/projects/{project_id}/users/{user_id}"

        payload = {"role": role}

        try:
            # Using POST as specified by the OpenAI API
            response = requests.post(url, headers=self.headers, json=payload)
            response.raise_for_status()

            logger.info(
                f"Successfully updated user {user_id} to role {role} in project {project_id}"
            )
            return True

        except requests.exceptions.RequestException as e:
            logger.error(
                f"Failed to update user {user_id} to role {role} in project {project_id}: {e}"
            )
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "text"):
                logger.error(f"Response: {e.response.text}")
            return False

    def list_projects(self) -> List[Dict]:
        """List all existing projects with pagination."""
        url = f"{self.base_url}/organization/projects"
        all_projects = []

        try:
            after = None
            while True:
                params = {"limit": 100}
                if after:
                    params["after"] = after

                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()

                projects_data = response.json()
                projects = projects_data.get("data", [])
                all_projects.extend(projects)

                # Check if there are more pages
                if not projects_data.get("has_more", False) or not projects:
                    break

                # Get cursor for next page
                after = projects[-1].get("id")

            logger.info(f"Found {len(all_projects)} existing projects")
            return all_projects

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to list projects: {e}")
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "text"):
                logger.error(f"Response: {e.response.text}")
            return []


def read_spreadsheet(file_path: str) -> List[Dict[str, str]]:
    """Read spreadsheet data (supports CSV and Excel formats)."""
    path = Path(file_path)  # Convert string to Path object

    if not path.exists():
        raise FileNotFoundError(f"Spreadsheet file not found: {file_path}")

    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(file_path)
        elif path.suffix.lower() in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")

        # Convert to list of dictionaries
        teams = df.to_dict("records")
        logger.info(f"Successfully read {len(teams)} teams from {file_path}")

        return teams

    except Exception as e:
        logger.error(f"Failed to read spreadsheet {file_path}: {e}")
        raise


def validate_team_data(teams: List[Dict]) -> List[Dict]:
    """Validate and clean team data."""
    valid_teams = []

    for i, team in enumerate(teams):
        # Check if required fields exist (case-insensitive)
        team_lower = {k.lower().strip(): v for k, v in team.items()}

        # Map HackWeek format columns to our expected fields
        project_name = None
        email = None
        description = None

        # Look for project name in slug format column
        for key in team_lower.keys():
            if "project name" in key and "slug" in key:
                project_name = str(team_lower[key]).strip()
                break

        # Look for email address
        for key in team_lower.keys():
            if "email address" in key:
                email = str(team_lower[key]).strip()
                break
            elif "email" in key:
                email = str(team_lower[key]).strip()
                break

        # Look for project description
        for key in team_lower.keys():
            if "brief description" in key and "hack week" in key:
                description = str(team_lower[key]).strip()
                break
            elif "description" in key:
                description = str(team_lower[key]).strip()
                break

        # Fallback: try common column name variations for backwards compatibility
        if not project_name:
            for key in team_lower.keys():
                if any(term in key for term in ["name", "team", "project"]):
                    project_name = str(team_lower[key]).strip()
                    break

        if not email:
            for key in team_lower.keys():
                if "mail" in key:
                    email = str(team_lower[key]).strip()
                    break

        if not project_name or not email:
            logger.warning(
                f"Row {i + 1}: Missing required fields (project name or email). Skipping."
            )
            continue

        if not project_name or not email or project_name == "nan" or email == "nan":
            logger.warning(f"Row {i + 1}: Empty project name or email. Skipping.")
            continue

        # Basic email validation
        if "@" not in email or "." not in email:
            logger.warning(f"Row {i + 1}: Invalid email format '{email}'. Skipping.")
            continue

        # Use description from CSV or fallback to default
        if not description or description == "nan":
            description = "Project created via automation script"

        # Limit description to 100 characters
        if len(description) > 100:
            description = description[:97] + "..."

        valid_teams.append(
            {
                "team_name": project_name,
                "email": email,
                "description": description,
            }
        )

    logger.info(f"Validated {len(valid_teams)} out of {len(teams)} teams")
    return valid_teams


def main():
    """Main execution function."""
    import argparse

    parser = argparse.ArgumentParser(description="Create OpenAI projects from spreadsheet")
    parser.add_argument("spreadsheet", help="Path to spreadsheet file (CSV or Excel)")
    parser.add_argument("--api-key", help="OpenAI API key (or set OPENAI_API_KEY env var)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without actually creating",
    )
    parser.add_argument(
        "--budget-limit",
        type=float,
        default=200.0,
        help="Budget limit in USD for each project (default: $200)",
    )
    parser.add_argument(
        "--alert-threshold",
        type=float,
        default=0.5,
        help="Budget alert threshold as fraction of limit (default: 0.5 = 50%%)",
    )
    parser.add_argument(
        "--auto-invite",
        action="store_true",
        default=True,
        help="Automatically invite users not found in organization (default: enabled)",
    )
    parser.add_argument(
        "--no-auto-invite",
        dest="auto_invite",
        action="store_false",
        help="Disable automatic user invitations",
    )

    args = parser.parse_args()

    # Get API key
    api_key = args.api_key
    if not api_key:
        import os

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error(
                "API key required. Use --api-key or set OPENAI_API_KEY environment variable"
            )
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
            # Budget settings disabled
            # logger.info(f"Budget settings: ${args.budget_limit:.2f} limit, ${args.budget_limit * args.alert_threshold:.2f} alert (at {args.alert_threshold*100:.0f}%)")
            for team in valid_teams:
                logger.info(f"  - Project: {team['team_name']} (User: {team['email']})")
                logger.info(f"    Description: {team['description']}")
            sys.exit(0)

        # Initialize OpenAI API manager
        openai_manager = OpenAIProjectManager(api_key)

        # Get existing projects to avoid duplicates
        existing_projects = openai_manager.list_projects()
        existing_names = {
            proj["name"].lower() for proj in existing_projects
        }  # Case-insensitive comparison
        existing_projects_by_name = {proj["name"].lower(): proj for proj in existing_projects}

        if existing_names:
            logger.info(f"Found existing projects: {[proj['name'] for proj in existing_projects]}")

        # Create projects
        created_count = 0
        processed_names = set()  # Track names we've processed in this batch

        for team in valid_teams:
            team_name = team["team_name"]
            email = team["email"]
            description = team["description"]

            # Check if we've already processed this project name in this batch
            if team_name.lower() in processed_names:
                logger.warning(f"Skipping duplicate project '{team_name}' found in CSV batch")
                continue

            # Check if project already exists (case-insensitive)
            if team_name.lower() in existing_names:
                logger.warning(
                    f"Project '{team_name}' already exists. Updating budget and checking if user needs to be added."
                )
                # Find the existing project ID
                existing_project = existing_projects_by_name.get(team_name.lower())
                if existing_project:
                    project_id = existing_project["id"]

                    # Set budget for existing project
                    # budget_set = openai_manager.set_project_budget(
                    #     project_id,
                    #     team_name,
                    #     args.budget_limit,
                    #     args.alert_threshold
                    # )

                    # Try to add user to existing project as owner
                    user_added = openai_manager.add_user_to_project(
                        project_id, email, "owner", args.auto_invite
                    )

                    if user_added:
                        logger.info(
                            f"Successfully added/updated user {email} as owner in project '{team_name}'"
                        )
                        created_count += 1
                    else:
                        logger.warning(
                            f"Failed to add/update user {email} to project '{team_name}'"
                        )

                processed_names.add(team_name.lower())
                continue

            # Create project with description from CSV
            project = openai_manager.create_project(team_name, description)
            if project:
                processed_names.add(team_name.lower())  # Mark as processed
                project_id = project["id"]

                # Budget setting disabled
                # budget_set = openai_manager.set_project_budget(
                #     project_id,
                #     team_name,
                #     args.budget_limit,
                #     args.alert_threshold
                # )

                # Add user to project as owner
                user_added = openai_manager.add_user_to_project(
                    project_id, email, "owner", args.auto_invite
                )

                if user_added:
                    logger.info(f"Project created and user added as owner for {team_name}")
                    created_count += 1
                else:
                    logger.warning(f"Project created but failed to add user {email}")
            else:
                logger.error(f"Failed to create project '{team_name}', skipping user addition")

        logger.info(f"Successfully processed {created_count} projects")

    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
