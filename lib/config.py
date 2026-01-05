#!/usr/bin/env python3
"""
OmegaConf-based configuration system for homely-vibes.

Replaces the old Constants.py pattern with hierarchical YAML configs:
- config/default.yaml: Safe defaults (checked into git)
- config/local.yaml: Secrets and overrides (gitignored)

Usage:
    from lib.config import get_config

    cfg = get_config()
    email = cfg.tesla.tesla_email
    tokens = cfg.pushover.tokens
"""

import os
from dataclasses import dataclass, field, is_dataclass
from typing import Dict, get_origin, get_args

from omegaconf import OmegaConf


@dataclass
class PathsConfig:
    """File paths and directories"""

    home: str = field(default_factory=lambda: os.environ.get("HOME", "/tmp"))
    logging_dir: str = ""  # Derived from home
    tokens_dir: str = "lib/tokens"
    tuya_log_base: str = ""  # Derived from home
    json_summary_file: str = ""  # Derived from home
    json_summary_patch_file: str = ""  # Derived from home (debugging)
    json_pumprates_file: str = ""  # Derived from home
    rachio_events_cmd: str = ""  # Derived from home

    def __post_init__(self) -> None:
        """Compute derived paths from home directory"""
        if not self.logging_dir:
            self.logging_dir = f"{self.home}/logs"
        if not self.tuya_log_base:
            self.tuya_log_base = f"{self.home}/tuya_logs/tuya_logs.csv"
        if not self.json_summary_file:
            self.json_summary_file = f"{self.home}/tuya_logs/summary.json"
        if not self.json_summary_patch_file:
            self.json_summary_patch_file = f"{self.home}/tuya_logs/summary.json"
        if not self.json_pumprates_file:
            self.json_pumprates_file = f"{self.home}/tuya_logs/pump_rates.json"
        if not self.rachio_events_cmd:
            self.rachio_events_cmd = f"{self.home}/bin/WaterLogging/get_rachio_events.js"


@dataclass
class EmailConfig:
    """Email configuration"""

    from_addr: str = "user@example.com"
    to_addr: str = "user@example.com"
    gmail_username: str = "user"
    gmail_password: str = ""


@dataclass
class TwilioConfig:
    """Twilio SMS configuration"""

    sid: str = ""
    auth_token: str = ""
    sms_from: str = "+18001234567"


@dataclass
class PushoverConfig:
    """Pushover notification configuration"""

    user: str = ""
    delivery_group: str = ""
    default_token: str = ""
    tokens: Dict[str, str] = field(
        default_factory=lambda: {
            "August": "",
            "NetworkCheck": "",
            "NodeCheck": "",
            "Powerwall": "",
            "RachioFlume": "",
            "SamsungFrame": "",
        }
    )


@dataclass
class NodeConfig:
    """Individual node configuration"""

    ip: str
    node_type: str  # "foscam", "windows", "generic"
    username: str | None = None
    password: str | None = None


@dataclass
class FoscamConfig:
    """Foscam camera configuration"""

    username: str = ""
    password: str = ""
    foscam_dir: str = "/mnt/IPCam_Data"
    purge_after_days: int = 90


@dataclass
class WindowsConfig:
    """Windows node credentials"""

    username: str = ""
    password: str = ""


@dataclass
class NodeCheckConfig:
    """Node monitoring configuration"""

    # Foscam and Windows credentials (used to build NODE_CONFIGS dict)
    foscam: FoscamConfig = field(default_factory=FoscamConfig)
    windows: WindowsConfig = field(default_factory=WindowsConfig)

    # NODE_CONFIGS dict - maps node name to NodeConfig
    node_configs: Dict[str, NodeConfig] = field(default_factory=dict)

    # NODES dict for BrowserAlert - maps node name to arbitrary config dict
    nodes: Dict[str, dict] = field(default_factory=dict)


@dataclass
class WaterMonitorConfig:
    """Water monitoring and alerting thresholds"""

    # Processing
    max_zones: int = 16
    max_new_files: int = 2
    logrotate_per_day: int = 4
    days_lookback: int = 90
    start_from_epoch: int = 1546329600  # 2019-01-01

    # Alerting
    days_email_report: int = 14
    min_drip_zone_alert_time: int = 1800
    min_drip_plot_time: int = 189
    min_misc_zone_alert_time: int = 86400  # SECONDS_IN_DAY
    min_sprinkler_zone_alert_time: int = 600
    alert_thresh: float = 1.18
    pump_alert: int = 22
    pump_toggles_count: int = 25


@dataclass
class OpModeConfig:
    """Tesla Powerwall operation mode configuration"""

    time_start: int
    time_end: int
    pct_gradient_per_hr: int
    pct_thresh: int
    iff_higher: bool
    pct_min: int
    pct_min_trail_stop: int
    op_mode: str  # "autonomous" or "self_consumption"
    reason: str
    always_notify: bool


@dataclass
class TeslaConfig:
    """Tesla Powerwall configuration"""

    powerwall_ip: str = "192.168.1.62"
    powerwall_email: str = ""
    powerwall_password: str = ""
    powerwall_sms_rcpt: str = ""
    powerwall_poll_time: int = 180

    tesla_email: str = ""
    tesla_password: str = ""
    tesla_token_file: str = "lib/tokens/tesla_tokens.json"

    # Powerwall decision points (complex nested config)
    decision_points: list[OpModeConfig] = field(default_factory=list)


@dataclass
class AugustConfig:
    """August Smart Locks configuration"""

    email: str = ""
    password: str = ""
    phone: str = ""
    token_file: str = "lib/tokens/august_auth_token.json"


@dataclass
class SamsungFrameConfig:
    """Samsung Frame TV configuration"""

    ip: str = "192.168.1.4"
    port: int = 8002
    token_file: str = "lib/tokens/samsung_frame_token.txt"
    default_matte: str = "shadowbox_black"
    supported_formats: list[str] = field(default_factory=lambda: ["jpg", "jpeg", "png"])
    max_image_size_mb: int = 10


@dataclass
class RachioConfig:
    """Rachio irrigation system configuration"""

    api_key: str = ""
    rachio_id: str = ""


@dataclass
class FlumeConfig:
    """Flume water monitoring configuration"""

    client_id: str = ""
    client_secret: str = ""
    user_email: str = ""
    password: str = ""


@dataclass
class NetworkCheckConfig:
    """Network bandwidth monitoring configuration"""

    min_dl_bw: int = 400  # Mbps
    min_ul_bw: int = 400  # Mbps


@dataclass
class BrowserAlertConfig:
    """Browser activity monitoring configuration"""

    refresh_delay: int = 30  # seconds
    min_reporting_gap: int = 6  # hours
    hr_start_monitoring: int = 2
    hr_stop_monitoring: int = 23
    hr_email: int = 19
    blacklist: list[str] = field(default_factory=list)


@dataclass
class Config:
    """Root configuration for homely-vibes"""

    # Module configs
    paths: PathsConfig = field(default_factory=PathsConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    twilio: TwilioConfig = field(default_factory=TwilioConfig)
    pushover: PushoverConfig = field(default_factory=PushoverConfig)
    node_check: NodeCheckConfig = field(default_factory=NodeCheckConfig)
    water_monitor: WaterMonitorConfig = field(default_factory=WaterMonitorConfig)
    tesla: TeslaConfig = field(default_factory=TeslaConfig)
    august: AugustConfig = field(default_factory=AugustConfig)
    samsung_frame: SamsungFrameConfig = field(default_factory=SamsungFrameConfig)
    rachio: RachioConfig = field(default_factory=RachioConfig)
    flume: FlumeConfig = field(default_factory=FlumeConfig)
    network_check: NetworkCheckConfig = field(default_factory=NetworkCheckConfig)
    browser_alert: BrowserAlertConfig = field(default_factory=BrowserAlertConfig)

    # Constants
    my_external_ip: str = "hoiboi.tplinkdns.com"
    seconds_in_day: int = 86400


# Singleton configuration instance
_config: Config | None = None


def get_config() -> Config:
    """
    Get application configuration singleton.

    Loads from config/default.yaml with optional config/local.yaml overrides.
    Config is cached after first load.

    Returns:
        Config: Application configuration
    """
    global _config
    if _config is None:
        config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config"))

        # Load default config
        default_path = os.path.join(config_dir, "default.yaml")
        local_path = os.path.join(config_dir, "local.yaml")

        # Load default configuration
        cfg_omega = OmegaConf.load(default_path)

        # Merge with local config if it exists
        if os.path.exists(local_path):
            local_cfg = OmegaConf.load(local_path)
            cfg_omega = OmegaConf.merge(cfg_omega, local_cfg)

        # Convert OmegaConf to Config dataclass
        # We use to_container to get a dict, then instantiate the dataclass
        cfg_dict = OmegaConf.to_container(cfg_omega, resolve=True)

        # Create Config instance from dict
        # Note: We need to manually construct nested dataclasses
        _config = _dict_to_config(cfg_dict)

    return _config


def _dict_to_config(cfg_dict: dict) -> Config:  # type: ignore
    """
    Convert configuration dictionary to Config dataclass.

    Handles nested dataclass construction.
    """

    # Helper to convert nested dicts to dataclasses
    def build_nested(data: dict, cls: type) -> object:  # type: ignore
        """Recursively build nested dataclasses"""
        kwargs = {}
        for field_name, field_type in cls.__annotations__.items():
            if field_name not in data:
                continue

            value = data[field_name]

            # Check if it's a generic type like list[OpModeConfig]
            origin = get_origin(field_type)

            if origin is list:
                # Handle list[SomeDataclass]
                args = get_args(field_type)
                if args and is_dataclass(args[0]):
                    # Convert each dict in the list to the dataclass
                    item_class = args[0]
                    kwargs[field_name] = [build_nested(item, item_class) for item in value]
                else:
                    # Plain list (e.g., list[str])
                    kwargs[field_name] = value
            elif origin is dict:
                # Handle dict types
                kwargs[field_name] = value
            elif is_dataclass(field_type):
                # Nested dataclass
                kwargs[field_name] = build_nested(value, field_type)
            else:
                # Primitive type
                kwargs[field_name] = value

        return cls(**kwargs)

    return build_nested(cfg_dict, Config)  # type: ignore


def reset_config() -> None:
    """Reset configuration singleton (useful for testing)"""
    global _config
    _config = None
