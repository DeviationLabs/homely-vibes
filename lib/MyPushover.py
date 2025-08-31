#!/usr/bin/env python3
import http.client
import urllib
import logging


class Pushover:
    """Pushover notification client."""

    def __init__(self, token: str, user: str):
        """Initialize Pushover client.

        Args:
            token: Pushover application token
            user: Pushover user key
        """
        self.token = token
        self.user = user

    def send_message(self, message: str, title: str = None, priority: int = 0) -> bool:
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
                payload["priority"] = priority

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
    # Example usage - in real code, pass actual token and user values
    from lib import Constants

    pushover = Pushover(Constants.POWERWALL_PUSHOVER_TOKEN, Constants.PUSHOVER_USER)
    pushover.send_message("test notification", title="Test")
