#!/usr/bin/env python3
import re
import time
import traceback
from lib import NetHelpers
import lib.Constants as Constants
from lib.logger import SystemLogger

logger = SystemLogger.get_logger(__name__)


class GenericNode:
    def __init__(self, name: str, config: Constants.NodeConfig):
        self.name = name
        self.config = config
        self.is_online = False

    def check_state(self, desired_up: bool = True, attempts: int = 5) -> bool:
        """Check if node is in desired state (up/down) - used for reboot verification"""
        for attempt in range(attempts):
            current_state = NetHelpers.ping_output(node=self.config.ip, desired_up=desired_up)
            logger.debug(
                f"{attempt=} for {self.name}, {desired_up=} In desired state: {current_state}"
            )
            if current_state == desired_up:
                self.is_online = current_state if desired_up else not current_state
                return True
            time.sleep(1)
        self.is_online = False if desired_up else True
        return False

    def heartbeat(self) -> bool:
        """Base health check - ping test. Subclasses should call super() then add specific checks"""
        self.is_online = NetHelpers.ping_output(node=self.config.ip, desired_up=True)
        logger.debug(f"Ping check for {self.name}: {self.is_online}")
        return self.is_online

    def reboot_node(self) -> str:
        """Reboot the node and return status message"""
        return "Reboot not supported for generic node"


class FoscamNode(GenericNode):
    def reboot_node(self) -> str:
        """Reboot Foscam camera via HTTP API"""
        cmd = "http://%s:88//cgi-bin/CGIProxy.fcgi?cmd=rebootSystem&usr=%s&pwd=%s" % (
            self.config.ip,
            self.config.username,
            self.config.password,
        )
        try:
            msg = str(NetHelpers.http_req(cmd))
            logger.info(f"Rebooted foscam node: {self.name}")
            return msg
        except OSError as e:
            err_msg = getattr(e, "message", repr(e))
            msg = f">> ERROR: When rebooting {self.name}. Got {err_msg[:100]}..."
            logger.error(msg)
            return msg

    def heartbeat(self) -> bool:
        """Check Foscam health: ping + image capture"""
        if not super().heartbeat():
                return False

        try:
            # Then do Foscam-specific image capture test
            from lib.FoscamImager import FoscamImager

            MAX_COUNT = 2
            for attempt in range(MAX_COUNT):
                try:
                    myCam = FoscamImager(self.config.ip, False)
                    image = myCam.getImage()
                    if image is not None:
                        logger.info(f"Got image from node: {self.name}")
                        return True
                except Exception as e:
                    logger.error(f"Attempt {attempt + 1}/{MAX_COUNT} failed for {self.name}: {e}")
                    logger.debug(traceback.format_exc())
                    if attempt < MAX_COUNT - 1:
                        time.sleep(30)

            logger.error(f"Failed to get image after {MAX_COUNT} attempts from: {self.name}")
            return False
        except Exception as e:
            pass
    
        return True


class WindowsNode(GenericNode):
    def reboot_node(self) -> str:
        """Reboot Windows machine via SSH"""
        winCmd = 'cmd /c "shutdown /r /f & ping localhost -n 3 > nul"'
        return str(
            NetHelpers.ssh_cmd(self.config.ip, self.config.username, self.config.password, winCmd)
        )

    def heartbeat(self) -> bool:
        """Check Windows health: ping + uptime statistics"""
        # First do base ping check
        if not super().heartbeat():
            return False

        # Then do Windows-specific uptime check
        winCmd = "net statistics workstation"
        output = str(
            NetHelpers.ssh_cmd(self.config.ip, self.config.username, self.config.password, winCmd)
        )
        if "successful" in output:
            match = re.search("Statistics since (.*)", output)
            if match:
                foundStr = match.group(1)
                logger.info(f"{self.name} is up since {foundStr}")
                return True
        return False
