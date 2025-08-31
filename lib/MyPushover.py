#!/usr/bin/env python3
import http.client
import urllib.parse
import logging
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

    def send_message(self, message: str, title: str|None = None, priority: int = 0) -> bool:
        """Send a message via Pushover.

        Args:
            message: The message to send
            title: Optional message title
            priority: Message priority (-2 to 2)

        Returns:
            True if message sent successfully, False otherwise
        """
        conn = http.client.HTTPSConnection("api.pushover.net:443")
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

            conn.request(
                "POST",
                "/1/messages.json",
                urllib.parse.urlencode(payload),
                {"Content-type": "application/x-www-form-urlencoded"},
            )
            resp = conn.getresponse()
            success = resp.status == 200

            if success:
                logging.debug(f"Pushover message sent successfully: {resp.status}")
            else:
                logging.warning(f"Pushover message failed: {resp.status} {resp.reason}")

            return success

        except Exception as e:
            logging.error(f"Error sending Pushover message: {e}")
            return False
        finally:
            conn.close()


if __name__ == "__main__":
    pushover = Pushover(Constants.PUSHOVER_USER, Constants.PUSHOVER_DEFAULT_TOKEN)
    pushover.send_message("test notification", title="Test")
