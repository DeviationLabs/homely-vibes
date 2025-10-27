#!/usr/bin/env python3
import logging
import requests
from lib import Constants


class Pushover:
    """Pushover notification client."""

    def __init__(self, user: str, token: str = Constants.PUSHOVER_DEFAULT_TOKEN):
        """Initialize Pushover client.

        Args:
            user: Pushover user key
            token: Pushover application token
        """
        self.user = user
        self.token = token

    def send_message(self, message: str, title: str | None = None, priority: int = 0) -> bool:
        """Send a message via Pushover.

        Args:
            message: The message to send
            title: Optional message title
            priority: Message priority (-2 to 2)

        Returns:
            True if message sent successfully, False otherwise
        """
        try:
            payload = {
                "token": self.token,
                "user": self.user,
                "message": message,
            }

            if title:
                payload["title"] = title

            if priority != 0:
                payload["priority"] = str(priority)

            resp = requests.post(
                "https://api.pushover.net/1/messages.json",
                data=payload,
                timeout=10,
            )
            success = resp.status_code == 200

            if success:
                logging.debug(f"Pushover message sent successfully: {resp.status_code}")
            else:
                logging.warning(f"Pushover message failed: {resp.status_code} {resp.reason}")

            return success

        except Exception as e:
            logging.error(f"Error sending Pushover message: {e}")
            return False


if __name__ == "__main__":
    pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_DEFAULT_TOKEN)
    pushover.send_message("test notification", title="Test")
