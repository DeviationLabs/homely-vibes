#!/usr/bin/env python3
import json
import re
import socket
import subprocess
import time
from lib import NetHelpers
from lib.config import NodeConfig
from lib.logger import SystemLogger

logger = SystemLogger.get_logger(__name__)

# 3 consecutive packet losses before a node is considered down. Matches the
# Nagios-style max_check_attempts=3 convention and tolerates a single radio sleep.
HEARTBEAT_PING_COUNT = 3


class GenericNode:
    def __init__(self, name: str, config: NodeConfig):
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
        self.is_online = NetHelpers.ping_output(
            node=self.config.ip, count=HEARTBEAT_PING_COUNT, desired_up=True
        )
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

        # TODO: Odroid is sigsegv on matplotlib
        # try:
        #     # Then do Foscam-specific image capture test
        #     from lib.FoscamImager import FoscamImager

        #     MAX_COUNT = 2
        #     for attempt in range(MAX_COUNT):
        #         try:
        #             myCam = FoscamImager(self.config.ip, False)
        #             image = myCam.getImage()
        #             if image is not None:
        #                 logger.info(f"Got image from node: {self.name}")
        #                 return True
        #         except Exception as e:
        #             logger.error(f"Attempt {attempt + 1}/{MAX_COUNT} failed for {self.name}: {e}")
        #             logger.debug(traceback.format_exc())
        #             if attempt < MAX_COUNT - 1:
        #                 time.sleep(30)

        #     logger.error(f"Failed to get image after {MAX_COUNT} attempts from: {self.name}")
        #     return False
        # except Exception:
        #     # not supported on this platform
        #     pass

        return True


class SomfyMyLinkNode(GenericNode):
    """Somfy myLink controller. Layered check: ping then JSON-RPC over TCP:44100."""

    DEFAULT_PORT = 44100
    RPC_TIMEOUT_S = 4

    def heartbeat(self) -> bool:
        """Check myLink health: ping + JSON-RPC mylink.status.info round-trip"""
        if not super().heartbeat():
            return False

        if not self.config.auth_token:
            # Ping-only fallback. A page on missing config would mean "operator forgot
            # a token", not "device is sick" — wrong signal for an emergency alert.
            logger.warning(f"{self.name}: no auth_token configured; myLink API check skipped")
            return True

        port = self.config.port or self.DEFAULT_PORT
        request = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "mylink.status.info",
                    "params": {"auth": self.config.auth_token},
                }
            )
            + "\n"
        ).encode()

        # myLink replies with one JSON object then keeps the connection open (no
        # newline / FIN). Parse incrementally and stop on first complete object —
        # waiting for a delimiter or EOF would block until socket timeout.
        try:
            with socket.create_connection(
                (self.config.ip, port), timeout=self.RPC_TIMEOUT_S
            ) as sock:
                sock.settimeout(self.RPC_TIMEOUT_S)
                sock.sendall(request)
                buf = b""
                response: dict | None = None
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break  # server closed
                    buf += chunk
                    try:
                        response = json.loads(buf.decode())
                        break  # got a complete object
                    except json.JSONDecodeError:
                        continue  # partial — keep reading
            if response is None:
                logger.warning(
                    f"{self.name}: myLink API check failed: incomplete response ({len(buf)} bytes)"
                )
                self.is_online = False
                return False
        except OSError as e:
            logger.warning(f"{self.name}: myLink API check failed: {e!r}")
            self.is_online = False
            return False

        if "error" in response:
            logger.warning(f"{self.name}: myLink RPC error: {response['error']}")
            self.is_online = False
            return False
        if "result" not in response:
            logger.warning(f"{self.name}: unexpected myLink response: {response!r}")
            self.is_online = False
            return False

        logger.debug(f"{self.name}: myLink API live, target={response['result'].get('targetID')}")
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


# WiFi devices in power-save (notably iPhones) drop ICMP replies but stay
# associated with the AP, so the router's ARP cache still has a valid MAC.
# ArpNode probes presence via the ARP cache instead of ICMP.
_MAC_RE = re.compile(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")


class ArpNode(GenericNode):
    def heartbeat(self) -> bool:
        # Fire one ping to trigger ARP resolution if the entry is stale.
        # Result is intentionally discarded — we only care about the ARP cache.
        NetHelpers.ping_output(node=self.config.ip, count=1, desired_up=True)
        try:
            result = subprocess.run(
                ["arp", "-n", self.config.ip],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.debug(f"ARP check for {self.name}: timeout")
            self.is_online = False
            return False

        stdout = result.stdout or ""
        has_mac = bool(_MAC_RE.search(stdout))
        is_incomplete = "incomplete" in stdout.lower()
        self.is_online = has_mac and not is_incomplete
        logger.debug(f"ARP check for {self.name}: {self.is_online} ({stdout!r})")
        return self.is_online
